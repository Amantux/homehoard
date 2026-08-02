"""Rank inventory matches and decide whether we are confident enough to act.

Resolving "drill" to an item is a guess. Acting on a wrong guess is how the
wrong thing gets moved, checked out, or edited — so resolution here returns a
CONFIDENCE, not just a best hit:

* **high** — act on the single match with no further questions.
* **low**  — hand back the top few candidates so the caller can ask which was
  meant. Callers must not act on a low-confidence result.

Ranking looks at labels, description and notes, not just the name, so "power
tools" or "warranty" finds things that only say so in their labels — and
``matched_on`` records WHY something matched so a caller can explain it.

Candidates carry **where** the thing lives, because location is the strongest
real-world disambiguator in an inventory: "Drill (power tools) — Garage" versus
"Drill bits (consumables) — Workshop" is a choice a person can actually make,
where two similar names alone are not.

This module is the single implementation of that policy. The MCP server and the
Home Assistant integration are separate processes, so they consume it through
the ``/resolve`` endpoint rather than importing it — the logic still lives in
exactly one place.
"""
from __future__ import annotations

# Score tiers. The gaps are deliberately wide so a stronger KIND of match always
# beats a weaker one regardless of how many weak matches pile up: an exact name
# outranks any prefix, a prefix outranks a bare substring, and a name match of
# any kind outranks label/description evidence.
SCORE_EXACT_NAME = 100
SCORE_NAME_PREFIX = 70
SCORE_NAME_CONTAINS = 50
SCORE_EXACT_LABEL = 40
SCORE_LABEL_CONTAINS = 25
SCORE_DESCRIPTION = 10

# "High confidence" means one of:
#   * a unique exact name match (handled below), or
#   * the top hit is at least a name-prefix match AND clears the runner-up by a
#     full tier.
# STRONG_SCORE is the prefix tier because a substring-only top hit ("drill"
# inside "Cordless Drill Charger") is genuinely weak evidence of intent.
# DOMINANCE_MARGIN of one tier means "Drill Press" (prefix, 70) wins over items
# merely labelled drill (25), while "Drill" vs "Drill bits" stays ambiguous —
# which it is.
STRONG_SCORE = SCORE_NAME_PREFIX
DOMINANCE_MARGIN = 30

MAX_CANDIDATES = 5
DESCRIPTION_SNIPPET = 140


def score_match(query: str, name: str, labels=None, description: str = ""):
    """``(score, matched_on)`` for one row against a query.

    ``matched_on`` is ``"name"``, ``"label"``, ``"description"``, or None when
    nothing matched (or the query is empty, where everything ties at 0).
    """
    q = (query or "").strip().casefold()
    if not q:
        return 0, None

    name_cf = (name or "").strip().casefold()
    if name_cf == q:
        return SCORE_EXACT_NAME, "name"
    if name_cf.startswith(q):
        return SCORE_NAME_PREFIX, "name"
    if q in name_cf:
        return SCORE_NAME_CONTAINS, "name"

    label_names = [str(lbl or "").strip().casefold() for lbl in (labels or [])]
    if any(lbl == q for lbl in label_names):
        return SCORE_EXACT_LABEL, "label"
    if any(q in lbl for lbl in label_names):
        return SCORE_LABEL_CONTAINS, "label"

    if q in (description or "").casefold():
        return SCORE_DESCRIPTION, "description"
    return 0, None


def _from_dict(row):
    """``(name, labels, description)`` from a serialized row.

    Labels may be objects (``{"name": ...}``) or plain strings. Description
    folds in notes so a match on either is found — both are free text the user
    wrote about the thing.
    """
    labels = row.get("labels") or []
    names = [lbl.get("name") if isinstance(lbl, dict) else lbl for lbl in labels]
    text = " ".join(str(row.get(k) or "") for k in ("description", "notes"))
    return row.get("name"), names, text


def rank(rows, query: str, *, get=None):
    """Sort ``rows`` best-match first, returning ``[(row, score, matched_on)]``.

    ``get(row) -> (name, labels, description)`` adapts whatever shape the caller
    holds; the default reads dict keys. Ties fall back to name order so results
    are stable rather than arbitrary.
    """
    get = get or _from_dict
    scored = []
    for row in rows:
        name, labels, description = get(row)
        score, matched_on = score_match(query, name, labels, description)
        scored.append((row, score, matched_on, (name or "").casefold()))
    scored.sort(key=lambda item: (-item[1], item[3]))
    return [(row, score, matched_on) for row, score, matched_on, _ in scored]


def is_confident(ranked) -> bool:
    """Whether the top of a ranked list is a safe single answer.

    True when there is only one match, when exactly one match is an exact name
    hit, or when the leader is a strong match that clears the runner-up by a
    tier. Everything else is a coin-flip and must be disambiguated.
    """
    if not ranked:
        return False
    if len(ranked) == 1:
        return True
    exact = [item for item in ranked if item[1] == SCORE_EXACT_NAME]
    if len(exact) == 1:
        return True
    if exact:
        return False  # several things share a name — never guess between them
    top, second = ranked[0][1], ranked[1][1]
    return top >= STRONG_SCORE and (top - second) >= DOMINANCE_MARGIN


def candidate_out(row, matched_on, score=None) -> dict:
    """The shape a caller shows a user when asking which thing was meant."""
    name, labels, description = _from_dict(row)
    text = (description or "").strip()
    if len(text) > DESCRIPTION_SNIPPET:
        text = text[:DESCRIPTION_SNIPPET].rstrip() + "…"
    out = {
        "id": row.get("id"),
        "name": name,
        "labels": [lbl for lbl in labels if lbl],
        "description": text,
        # Where it lives — the disambiguator that actually settles it.
        "where": row.get("where") or "",
        "matchedOn": matched_on,
    }
    if row.get("type"):
        out["type"] = row["type"]
    if score is not None:
        out["score"] = score
    return out


def decide(rows, query: str, limit: int = MAX_CANDIDATES) -> dict:
    """Rank ``rows`` and return a confidence decision.

    ``{"confidence": "high", "match": row, "matchedOn": ...}`` when it is safe to
    act, ``{"confidence": "low", "candidates": [...]}`` when the caller must ask,
    or ``{"confidence": "none", "candidates": []}`` when nothing matched.
    """
    ranked = [item for item in rank(rows, query) if item[1] > 0 or not query]
    if not ranked:
        return {"confidence": "none", "candidates": []}
    if is_confident(ranked):
        row, score, matched_on = ranked[0]
        return {"confidence": "high", "match": row, "matchedOn": matched_on,
                "score": score}
    return {
        "confidence": "low",
        "candidates": [
            candidate_out(row, matched_on, score)
            for row, score, matched_on in ranked[:limit]
        ],
    }
