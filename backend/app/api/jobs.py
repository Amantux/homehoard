"""Background-job endpoints: enqueue an async task, poll its progress.

Jobs are group-scoped. Enqueuing bulk AI tooling is owner-only (external, paid
calls); reading progress is any group member. The worker (worker.py) runs them.
"""
from flask import Blueprint, jsonify, request, abort

from ..extensions import db
from ..models import Job
from ..auth import login_required, owner_required, current_group
from ..schemas.serializers import job_out
from ..services.jobs import enqueue, known_kinds, JobError

bp = Blueprint("jobs", __name__)


def _get_job(job_id) -> Job:
    j = db.session.get(Job, job_id)
    if not j or j.group_id != current_group().id:
        abort(404)
    return j


@bp.post("/jobs/<kind>")
@owner_required
def create_job(kind):
    """Enqueue (or resume) a background job of this kind for the group."""
    if kind not in known_kinds():
        return jsonify({"error": f"unknown job kind '{kind}'"}), 404
    try:
        job = enqueue(kind, current_group().id)
    except JobError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(job_out(job)), 202


@bp.get("/jobs/<job_id>")
@login_required
def get_job(job_id):
    """Poll one job's status/progress."""
    return jsonify(job_out(_get_job(job_id)))


@bp.get("/jobs")
@login_required
def list_jobs():
    """The group's most recent jobs, newest first. Optional ?kind= filter — handy
    for the UI to find/resume the latest job of a kind."""
    q = db.session.query(Job).filter(Job.group_id == current_group().id)
    kind = request.args.get("kind")
    if kind:
        q = q.filter(Job.kind == kind)
    jobs = q.order_by(Job.created_at.desc()).limit(20).all()
    return jsonify({"items": [job_out(j) for j in jobs]})
