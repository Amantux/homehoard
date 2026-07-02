from datetime import datetime

from flask import Blueprint, request, jsonify, abort

from ..extensions import db
from ..models import Item, MaintenanceEntry
from ..auth import login_required, current_group
from ..schemas.serializers import maintenance_out

bp = Blueprint("maintenance", __name__)


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _get_item(item_id) -> Item:
    item = db.session.get(Item, item_id)
    if not item or item.group_id != current_group().id:
        abort(404)
    return item


@bp.get("/maintenance")
@login_required
def all_maintenance():
    """Aggregate maintenance across the whole group (for the Maintenance page)."""
    entries = (
        db.session.query(MaintenanceEntry)
        .join(Item, Item.id == MaintenanceEntry.item_id)
        .filter(Item.group_id == current_group().id)
        .all()
    )
    status = request.args.get("status")  # scheduled | completed | both
    now = datetime.utcnow()
    out = []
    for e in entries:
        is_completed = e.completed_date is not None
        if status == "scheduled" and is_completed:
            continue
        if status == "completed" and not is_completed:
            continue
        data = maintenance_out(e)
        data["itemName"] = e.item.name if e.item else None
        data["status"] = "completed" if is_completed else "scheduled"
        data["overdue"] = bool(
            not is_completed and e.scheduled_date and e.scheduled_date < now
        )
        out.append(data)
    out.sort(
        key=lambda d: d.get("completedDate") or d.get("scheduledDate") or "",
        reverse=True,
    )
    return jsonify(
        {
            "entries": out,
            "costTotal": sum(e.cost or 0 for e in entries if e.completed_date),
        }
    )


@bp.get("/items/<item_id>/maintenance")
@login_required
def list_entries(item_id):
    item = _get_item(item_id)
    entries = sorted(
        item.maintenance_entries,
        key=lambda e: e.completed_date or e.scheduled_date or e.created_at,
        reverse=True,
    )
    completed = [e for e in entries if e.completed_date]
    cost = sum(e.cost or 0 for e in completed)
    avg = cost / len(completed) if completed else 0
    return jsonify(
        {
            "entries": [maintenance_out(e) for e in entries],
            "costTotal": cost,
            "costAverage": avg,
        }
    )


@bp.post("/items/<item_id>/maintenance")
@login_required
def create_entry(item_id):
    item = _get_item(item_id)
    data = request.get_json(force=True) or {}
    entry = MaintenanceEntry(
        name=data.get("name", ""),
        description=data.get("description", ""),
        cost=data.get("cost", 0) or 0,
        scheduled_date=_parse_dt(data.get("scheduledDate")),
        completed_date=_parse_dt(data.get("completedDate")),
        item_id=item.id,
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify(maintenance_out(entry)), 201


@bp.put("/items/<item_id>/maintenance/<entry_id>")
@login_required
def update_entry(item_id, entry_id):
    _get_item(item_id)
    entry = db.session.get(MaintenanceEntry, entry_id)
    if not entry or entry.item_id != item_id:
        abort(404)
    data = request.get_json(force=True) or {}
    if "name" in data:
        entry.name = data["name"]
    if "description" in data:
        entry.description = data["description"]
    if "cost" in data:
        entry.cost = data["cost"] or 0
    if "scheduledDate" in data:
        entry.scheduled_date = _parse_dt(data["scheduledDate"])
    if "completedDate" in data:
        entry.completed_date = _parse_dt(data["completedDate"])
    db.session.commit()
    return jsonify(maintenance_out(entry))


@bp.delete("/items/<item_id>/maintenance/<entry_id>")
@login_required
def delete_entry(item_id, entry_id):
    _get_item(item_id)
    entry = db.session.get(MaintenanceEntry, entry_id)
    if not entry or entry.item_id != item_id:
        abort(404)
    db.session.delete(entry)
    db.session.commit()
    return "", 204
