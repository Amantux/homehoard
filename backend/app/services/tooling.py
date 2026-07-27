"""AI tooling jobs: auto-categorize items (assign labels) and propose clusters.

Both run in the background (services/jobs). Suggestions are **confidence-gated**: a
high-confidence categorize label that already exists is applied automatically;
everything else lands in the review queue (``AiSuggestion``, status ``pending``).
Review decisions (accepted / rejected) are fed back as few-shot **in-context
learning** examples to later runs, so the model learns the household's preferences.
"""
from __future__ import annotations

import json
import logging

from flask import current_app

from ..extensions import db
from ..models import AiSuggestion, Item, Label, utcnow

_LOGGER = logging.getLogger("homehoard.tooling")
_CATEGORIZE_MAX = 200   # items per run
_CLUSTER_ITEMS_MAX = 300  # items fed to the clusterer


def _threshold() -> float:
    return float(current_app.config.get("AI_CONFIDENCE_THRESHOLD", 0.8))


def _confidence(value) -> float:
    """Coerce a model-reported confidence to a clamped [0,1] float. A hallucinated
    non-numeric or out-of-range value must never crash the job or auto-apply."""
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, c))


def existing_labels(gid) -> list[str]:
    return [lb.name for lb in db.session.query(Label)
            .filter_by(group_id=gid).order_by(Label.name.asc()).all()]


def _find_label(gid, name):
    if not name:
        return None
    return (db.session.query(Label)
            .filter(Label.group_id == gid, db.func.lower(Label.name) == name.lower())
            .first())


def _example_text(sugg) -> str:
    return sugg.item.name if sugg.item else sugg.label


def icl_examples(gid, kind, limit=8) -> str:
    """Recent accepted (good) + rejected (bad) decisions as few-shot guidance."""
    rows = (db.session.query(AiSuggestion)
            .filter(AiSuggestion.group_id == gid, AiSuggestion.kind == kind,
                    AiSuggestion.status.in_(("accepted", "rejected")))
            .order_by(AiSuggestion.resolved_at.desc()).limit(limit * 3).all())
    pos = [r for r in rows if r.status == "accepted"][:limit]
    neg = [r for r in rows if r.status == "rejected"][:limit]
    parts = []
    if pos:
        parts.append("Labels the user ACCEPTED (do more like these): "
                     + "; ".join(f"'{_example_text(r)}' → {r.label}" for r in pos))
    if neg:
        parts.append("Labels the user REJECTED (avoid these): "
                     + "; ".join(f"'{_example_text(r)}' → {r.label}" for r in neg))
    return "\n".join(parts)


def _job_provider(opts: dict):
    """The provider for a job run: a per-run override if given, else the configured
    default. Raises JobError (→ job errored) when unavailable."""
    from .ai.base import ProviderError
    from .ai.registry import get_provider, provider_for
    from .jobs import JobError
    try:
        if opts.get("provider") or opts.get("model"):
            return provider_for(opts.get("provider"), opts.get("model"))
        return get_provider()
    except ProviderError as exc:
        raise JobError(str(exc)) from exc


# --- categorize ------------------------------------------------------------
def categorize_item(item, labels, examples, note, provider) -> dict | None:
    """One provider call → {label, confidence, rationale}, or None on failure."""
    desc = f"{item.name}. {item.description or ''} {item.search_text or ''}".strip()[:400]
    prompt = (
        "Assign the single best label to this home-inventory item. Prefer an existing "
        "label if one fits; only propose a NEW label if none do.\n"
        f"Existing labels: {', '.join(labels) or '(none yet)'}\n"
        + (f"{examples}\n" if examples else "")
        + (f"User guidance: {note}\n" if note else "")
        + f"Item: {desc}\n"
        'Respond ONLY as JSON: {"label": "<name>", "confidence": 0.0-1.0, "rationale": "<short>"}.'
    )
    try:
        data = provider.complete_json(prompt)
        return {"label": (data.get("label") or "").strip(),
                "confidence": data.get("confidence"),
                "rationale": (data.get("rationale") or "").strip()}
    except Exception as exc:  # noqa: BLE001 - best-effort; skip this item
        _LOGGER.info("categorize failed for %s: %s", item.id, exc)
        return None


def run_categorize(job) -> dict:
    from .jobs import bump
    gid = job.group_id
    opts = json.loads(job.params) if job.params else {}
    note = str(opts.get("note") or "")
    provider = _job_provider(opts)
    labels = existing_labels(gid)
    examples = icl_examples(gid, "categorize")
    threshold = _threshold()

    items = (db.session.query(Item)
             .filter(Item.group_id == gid, Item.archived.is_(False))
             .filter(~Item.labels.any())  # only items with no labels yet
             .order_by(Item.created_at.asc()).limit(_CATEGORIZE_MAX).all())
    bump(job, done=0, total=len(items))
    applied = queued = 0
    for i, item in enumerate(items, 1):
        out = categorize_item(item, labels, examples, note, provider)
        name = (out or {}).get("label") if out else None
        if name:
            name = name[:255]
            conf = _confidence(out.get("confidence"))
            existing = _find_label(gid, name)
            common = dict(kind="categorize", label=name, confidence=conf,
                          rationale=(out.get("rationale") or "")[:500],
                          item_id=item.id, group_id=gid)
            if conf >= threshold and existing is not None:
                if existing not in item.labels:
                    item.labels.append(existing)
                db.session.add(AiSuggestion(status="accepted", resolved_at=utcnow(), **common))
                applied += 1
            else:
                db.session.add(AiSuggestion(status="pending", **common))
                queued += 1
        bump(job, done=i)  # commits progress + this item's writes + heartbeat
    return {"applied": applied, "queued": queued, "scanned": len(items)}


# --- cluster ---------------------------------------------------------------
def cluster_items(items, note, provider) -> list[dict]:
    """One provider call → [{name, confidence, rationale, itemIds}]. Items are fed by
    index (not id) to keep the prompt short; indices are mapped back to ids here."""
    listing = "\n".join(f"{idx}: {it.name}" for idx, it in enumerate(items))
    prompt = (
        "Group these home-inventory items into a few meaningful named collections "
        "(e.g. 'Camping gear', 'Kids winter clothes'). Only group items that clearly "
        "belong together; leave unrelated items out.\n"
        + (f"User guidance: {note}\n" if note else "")
        + f"Items (index: name):\n{listing}\n"
        'Respond ONLY as JSON: {"clusters": [{"name": "...", "indices": [0,3,7], '
        '"confidence": 0.0-1.0}]}.'
    )
    try:
        data = provider.complete_json(prompt, max_tokens=1500)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.info("cluster failed: %s", exc)
        return []
    out = []
    for c in (data.get("clusters") or []):
        # Dedupe + drop out-of-range / bool (JSON true→1) indices the model may hallucinate.
        seen, idxs = set(), []
        for n in (c.get("indices") or []):
            if isinstance(n, int) and not isinstance(n, bool) and 0 <= n < len(items) and n not in seen:
                seen.add(n)
                idxs.append(n)
        out.append({"name": c.get("name"), "confidence": c.get("confidence"),
                    "rationale": c.get("rationale", ""),
                    "itemIds": [items[n].id for n in idxs]})
    return out


def run_cluster(job) -> dict:
    from .jobs import bump
    gid = job.group_id
    opts = json.loads(job.params) if job.params else {}
    note = str(opts.get("note") or "")
    provider = _job_provider(opts)
    items = (db.session.query(Item)
             .filter(Item.group_id == gid, Item.archived.is_(False))
             .order_by(Item.created_at.asc()).limit(_CLUSTER_ITEMS_MAX).all())
    bump(job, done=0, total=1)
    if not items:
        return {"proposed": 0, "scanned": 0}
    valid_ids = {it.id for it in items}
    proposed = 0
    for c in cluster_items(items, note, provider):
        name = (c.get("name") or "").strip()[:255]
        ids = [i for i in (c.get("itemIds") or []) if i in valid_ids]
        if not name or len(ids) < 2:  # skip trivial / empty clusters
            continue
        db.session.add(AiSuggestion(
            kind="cluster", status="pending", label=name,
            confidence=_confidence(c.get("confidence")),
            rationale=(c.get("rationale") or "")[:500],
            payload=json.dumps({"itemIds": ids}), group_id=gid))
        proposed += 1
    bump(job, done=1, total=1)
    return {"proposed": proposed, "scanned": len(items)}


# --- apply / reject (review actions) --------------------------------------
def apply_suggestion(sugg) -> dict:
    """Accept a pending suggestion: attach its label (creating it if new) to the item
    (categorize) or every member item (cluster). Idempotent; group-scoped."""
    gid = sugg.group_id
    label = _find_label(gid, sugg.label)
    if label is None:
        label = Label(name=sugg.label[:255], group_id=gid)
        db.session.add(label)
        db.session.flush()

    targets = []
    if sugg.kind == "categorize" and sugg.item_id:
        it = db.session.get(Item, sugg.item_id)
        if it and it.group_id == gid:
            targets = [it]
    elif sugg.kind == "cluster":
        ids = (json.loads(sugg.payload) if sugg.payload else {}).get("itemIds", [])
        targets = [it for it in (db.session.get(Item, i) for i in ids)
                   if it and it.group_id == gid]
    for it in targets:
        if label not in it.labels:
            it.labels.append(label)
    sugg.status = "accepted"
    sugg.resolved_at = utcnow()
    db.session.commit()
    return {"applied": len(targets), "label": label.name}


def reject_suggestion(sugg) -> None:
    sugg.status = "rejected"
    sugg.resolved_at = utcnow()
    db.session.commit()
