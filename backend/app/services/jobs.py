"""Background job queue — DB-backed, worker-polled, safe across gunicorn workers.

A job is a row in ``jobs`` (kind, status, total/done progress, result/error). The
worker poller (see ``worker.py``) claims pending jobs with an **atomic
compare-and-swap** UPDATE, so the two gunicorn workers never run the same job. A
handler updates progress as it goes and returns a JSON-serializable result summary;
a killed worker leaves a stale ``running`` row that ``reap_stale`` returns to
``pending`` for another worker to pick up.

Handlers are registered per kind. Each runs inside an app context with the job's
``group_id`` as the tenant scope.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Job, utcnow

_LOGGER = logging.getLogger("homehoard.jobs")

# Jobs left "running" longer than this (a worker died mid-run) are requeued.
STALE_AFTER_S = 20 * 60

_HANDLERS: dict[str, callable] = {}


class JobError(RuntimeError):
    """A handler failure that should mark the job errored with this message."""


def register(kind: str):
    def deco(fn):
        _HANDLERS[kind] = fn
        return fn
    return deco


def known_kinds() -> tuple[str, ...]:
    return tuple(_HANDLERS)


def _active_job(gid: str, kind: str) -> Job | None:
    return (db.session.query(Job)
            .filter(Job.group_id == gid, Job.kind == kind,
                    Job.status.in_(("pending", "running")))
            .first())


def enqueue(kind: str, gid: str, params: dict | None = None) -> Job:
    """Create a pending job, or return the group's existing active job of this kind.

    ``params`` are per-run options (e.g. enrich {note, provider, model}) stored as
    JSON. One active job per group+kind is enforced by a partial unique index, so two
    concurrent enqueues (double-click, two tabs) can't both create one — the loser's
    INSERT hits the constraint and we return the winner instead of racing two jobs.
    """
    if kind not in _HANDLERS:
        raise JobError(f"unknown job kind '{kind}'")
    existing = _active_job(gid, kind)
    if existing:
        return existing
    job = Job(kind=kind, group_id=gid, status="pending",
              params=json.dumps(params) if params else "")
    db.session.add(job)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _active_job(gid, kind)  # concurrent enqueue won; use its job
    return job


def claim_one() -> Job | None:
    """Atomically claim the oldest pending job. Returns the claimed job, or None if
    none pending / another worker won the race (caller simply polls again)."""
    row = (db.session.query(Job.id).filter(Job.status == "pending")
           .order_by(Job.created_at.asc()).first())
    if not row:
        return None
    # Compare-and-swap: only the worker whose UPDATE flips 'pending'→'running' wins.
    updated = (db.session.query(Job)
               .filter(Job.id == row[0], Job.status == "pending")
               .update({"status": "running", "started_at": utcnow()}))
    db.session.commit()
    return db.session.get(Job, row[0]) if updated == 1 else None


def run_job(job: Job) -> None:
    """Execute a claimed job's handler; record result or error. Never raises."""
    handler = _HANDLERS.get(job.kind)
    try:
        if handler is None:
            raise JobError(f"no handler for kind '{job.kind}'")
        summary = handler(job) or {}
        job.result = json.dumps(summary)
        job.status = "done"
        job.error = ""
    except Exception as exc:  # noqa: BLE001 - any failure marks the job errored
        db.session.rollback()
        _LOGGER.exception("job %s (%s) failed", job.id, job.kind)
        job = db.session.get(Job, job.id)  # reattach after rollback
        if job:
            job.status = "error"
            job.error = str(exc)[:500]
    db.session.commit()


def reap_stale() -> int:
    """Return jobs stuck 'running' past the stale window to 'pending' (worker died).
    Returns how many were requeued."""
    from datetime import timedelta
    cutoff = utcnow() - timedelta(seconds=STALE_AFTER_S)
    n = (db.session.query(Job)
         .filter(Job.status == "running", Job.started_at < cutoff)
         .update({"status": "pending", "started_at": None}))
    db.session.commit()
    return n


def bump(job: Job, done: int | None = None, total: int | None = None) -> None:
    """Persist incremental progress so the polling UI sees it and partial work
    survives a worker kill. Also HEARTBEATS ``started_at`` — the poller thread is
    blocked in run_job for the job's whole duration and can't reap itself, so a
    long-but-live job must keep refreshing its stale clock or a sibling worker would
    reap and double-run it. reap_stale fires only when heartbeats stop (worker died)."""
    if total is not None:
        job.total = total
    if done is not None:
        job.done = done
    job.started_at = utcnow()
    db.session.commit()


# --- handlers --------------------------------------------------------------
# Cap items enriched per job run (bounded memory + runtime for a huge inventory);
# the result reports how many still lack a description so the UI can run again.
_ENRICH_MAX = 200


@register("enrich")
def _enrich_job(job: Job) -> dict:
    """Describe items missing a search_text (up to _ENRICH_MAX per run), via the
    configured provider + Ollama web search. Commits per item so progress + partial
    results survive a worker kill."""
    from . import enrich
    from .ai.base import ProviderError
    from .ai.registry import resolve_job_provider
    from ..api.items import _apply_description, _describe_fields  # local: api↔services
    from ..models import Item

    if not enrich.enabled():
        raise JobError("Web search isn't configured (set an Ollama search key).")
    gid = job.group_id
    opts = json.loads(job.params) if job.params else {}
    note = str(opts.get("note") or "")
    # Provider precedence: per-run override > the stored "Enrichment" async
    # preference > None (→ describe() falls back to the configured chat provider).
    try:
        provider = resolve_job_provider("enrich", opts)
    except ProviderError as exc:
        raise JobError(str(exc)) from exc

    def missing_q():
        return (db.session.query(Item)
                .filter(Item.group_id == gid, Item.archived.is_(False),
                        db.or_(Item.search_text.is_(None), Item.search_text == "")))

    items = missing_q().order_by(Item.created_at.asc()).limit(_ENRICH_MAX).all()
    bump(job, done=0, total=len(items))
    described = 0
    for i, item in enumerate(items, 1):
        result = enrich.describe(_describe_fields(item), provider=provider, note=note)
        if result:
            _apply_description(item, result)
            described += 1
        bump(job, done=i)  # commits the description + progress + heartbeat together
    return {"described": described, "scanned": len(items), "remaining": missing_q().count()}


@register("categorize")
def _categorize_job(job: Job) -> dict:
    """Assign a label to each unlabeled item — high-confidence matches auto-apply,
    the rest go to the review queue (see services/tooling)."""
    from .tooling import run_categorize
    return run_categorize(job)


@register("cluster")
def _cluster_job(job: Job) -> dict:
    """Propose named groupings over the collection for review (services/tooling)."""
    from .tooling import run_cluster
    return run_cluster(job)
