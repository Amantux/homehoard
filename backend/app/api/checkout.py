"""Check items in and out — 'yes it's here' vs 'no, it's out'."""
from datetime import datetime

from flask import Blueprint, request, jsonify, abort

from ..extensions import db
from ..models import Item, CheckoutEntry
from ..auth import login_required, current_group
from ..schemas.serializers import item_out, item_summary, checkout_out

bp = Blueprint("checkout", __name__)


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


@bp.post("/items/<item_id>/checkout")
@login_required
def check_out(item_id):
    item = _get_item(item_id)
    if item.checked_out:
        return jsonify({"error": "already checked out",
                        "checkedOutTo": item.checked_out_to}), 409
    data = request.get_json(silent=True) or {}
    item.checked_out = True
    item.checked_out_to = (data.get("person") or "").strip()
    item.checked_out_at = datetime.utcnow()
    item.checkout_due = _parse_dt(data.get("due"))
    db.session.add(
        CheckoutEntry(
            action="out", person=item.checked_out_to,
            notes=data.get("notes", ""), due=item.checkout_due, item_id=item.id,
        )
    )
    db.session.commit()
    return jsonify(item_out(item))


@bp.post("/items/<item_id>/checkin")
@login_required
def check_in(item_id):
    item = _get_item(item_id)
    if not item.checked_out:
        return jsonify({"error": "not checked out"}), 409
    data = request.get_json(silent=True) or {}
    db.session.add(
        CheckoutEntry(
            action="in", person=item.checked_out_to,
            notes=data.get("notes", ""), item_id=item.id,
        )
    )
    item.checked_out = False
    item.checked_out_to = ""
    item.checked_out_at = None
    item.checkout_due = None
    db.session.commit()
    return jsonify(item_out(item))


@bp.get("/items/<item_id>/checkout")
@login_required
def history(item_id):
    item = _get_item(item_id)
    entries = sorted(item.checkout_entries, key=lambda e: e.created_at, reverse=True)
    return jsonify(
        {
            "checkedOut": item.checked_out,
            "checkedOutTo": item.checked_out_to,
            "history": [checkout_out(e) for e in entries],
        }
    )


@bp.get("/checkouts")
@login_required
def all_checked_out():
    """Every item currently checked out — 'who has what'."""
    items = (
        db.session.query(Item)
        .filter_by(group_id=current_group().id, checked_out=True)
        .order_by(Item.checked_out_at.asc())
        .all()
    )
    now = datetime.utcnow()
    out = []
    for i in items:
        data = item_summary(i)
        data["checkedOutTo"] = i.checked_out_to
        data["checkedOutAt"] = i.checked_out_at.isoformat() if i.checked_out_at else None
        data["checkoutDue"] = i.checkout_due.isoformat() if i.checkout_due else None
        data["overdue"] = bool(i.checkout_due and i.checkout_due < now)
        out.append(data)
    return jsonify({"items": out, "total": len(out)})
