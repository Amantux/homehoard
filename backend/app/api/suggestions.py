"""AI suggestion review queue: list pending categorize/cluster proposals, and
accept (apply) or reject them. Accept/reject decisions become few-shot examples
for later tooling runs. Group-scoped."""
import json

from flask import Blueprint, jsonify, request, abort
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models import AiSuggestion, Item
from ..auth import login_required, current_group
from ..services.tooling import apply_suggestion, reject_suggestion

bp = Blueprint("suggestions", __name__)


def _out(s, names=None) -> dict:
    """Serialize a suggestion. ``names`` is an id→name map used to resolve cluster
    members without a per-row query (see list_suggestions)."""
    d = {
        "id": s.id, "kind": s.kind, "status": s.status, "label": s.label,
        "confidence": s.confidence, "rationale": s.rationale,
        "createdAt": s.created_at.isoformat() if s.created_at else None,
    }
    if s.kind == "categorize":
        d["item"] = {"id": s.item.id, "name": s.item.name} if s.item else None
    else:
        ids = (json.loads(s.payload) if s.payload else {}).get("itemIds", [])
        names = names if names is not None else _member_names(ids, s.group_id)
        d["members"] = [{"id": i, "name": names[i]} for i in ids if i in names]
    return d


def _member_names(ids, gid) -> dict:
    if not ids:
        return {}
    rows = (db.session.query(Item.id, Item.name)
            .filter(Item.group_id == gid, Item.id.in_(ids)).all())
    return {r[0]: r[1] for r in rows}


def _get(sugg_id) -> AiSuggestion:
    s = db.session.get(AiSuggestion, sugg_id)
    if not s or s.group_id != current_group().id:
        abort(404)
    return s


@bp.get("/suggestions")
@login_required
def list_suggestions():
    """The review queue. ?kind=categorize|cluster and ?status=pending|accepted|rejected
    (default pending), newest first."""
    gid = current_group().id
    q = (db.session.query(AiSuggestion)
         .options(selectinload(AiSuggestion.item))  # avoid per-row item lazy-load
         .filter(AiSuggestion.group_id == gid))
    kind = request.args.get("kind")
    if kind:
        q = q.filter(AiSuggestion.kind == kind)
    q = q.filter(AiSuggestion.status == request.args.get("status", "pending"))
    rows = q.order_by(AiSuggestion.created_at.desc()).limit(200).all()
    # Batch-resolve every cluster row's member names in one query, not per row.
    ids = [i for s in rows if s.kind == "cluster"
           for i in (json.loads(s.payload) if s.payload else {}).get("itemIds", [])]
    names = _member_names(ids, gid)
    return jsonify({"items": [_out(s, names) for s in rows]})


@bp.post("/suggestions/<sugg_id>/accept")
@login_required
def accept(sugg_id):
    s = _get(sugg_id)
    if s.status != "pending":
        return jsonify({"error": "already resolved"}), 409
    return jsonify(apply_suggestion(s))


@bp.post("/suggestions/<sugg_id>/reject")
@login_required
def reject(sugg_id):
    s = _get(sugg_id)
    if s.status != "pending":
        return jsonify({"error": "already resolved"}), 409
    reject_suggestion(s)
    return jsonify({"rejected": True})
