import secrets
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify

from ..extensions import db
from ..models import GroupInvitation, Item, Label, Location, User
from ..auth import login_required, owner_required, current_group
from ..schemas.serializers import group_out

bp = Blueprint("groups", __name__)


@bp.get("/groups")
@login_required
def get_group():
    return jsonify(group_out(current_group()))


@bp.put("/groups")
@owner_required
def update_group():
    data = request.get_json(force=True) or {}
    group = current_group()
    if "name" in data:
        group.name = data["name"]
    if "currency" in data:
        group.currency = data["currency"]
    db.session.commit()
    return jsonify(group_out(group))


@bp.post("/groups/invitations")
@owner_required
def create_invitation():
    data = request.get_json(force=True) or {}
    group = current_group()
    uses = int(data.get("uses", 1))
    days = int(data.get("expiresAt", 7)) if isinstance(data.get("expiresAt"), int) else 7
    token = secrets.token_urlsafe(24)
    inv = GroupInvitation(
        token=token,
        uses=uses,
        expires_at=(datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
        group_id=group.id,
    )
    db.session.add(inv)
    db.session.commit()
    return jsonify({"token": token, "uses": uses, "expiresAt": inv.expires_at}), 201


@bp.get("/groups/statistics")
@login_required
def statistics():
    group = current_group()
    items = db.session.query(Item).filter_by(group_id=group.id).all()
    total_price = sum((i.purchase_price or 0) * (i.quantity or 1) for i in items)
    return jsonify(
        {
            "totalItems": len(items),
            "totalLabels": db.session.query(Label).filter_by(group_id=group.id).count(),
            "totalLocations": db.session.query(Location)
            .filter_by(group_id=group.id)
            .count(),
            "totalUsers": db.session.query(User).filter_by(group_id=group.id).count(),
            "totalWithWarranty": sum(
                1 for i in items if i.lifetime_warranty or i.warranty_expires
            ),
            "totalItemPrice": total_price,
        }
    )


@bp.get("/groups/statistics/purchase-price")
@login_required
def purchase_price_stats():
    """Time-series of purchase price. Simplified monthly aggregation."""
    group = current_group()
    items = (
        db.session.query(Item)
        .filter(Item.group_id == group.id, Item.purchase_date.isnot(None))
        .all()
    )
    buckets = {}
    for i in items:
        key = i.purchase_date.strftime("%Y-%m")
        buckets[key] = buckets.get(key, 0) + (i.purchase_price or 0) * (i.quantity or 1)
    entries = [{"date": k, "value": v} for k, v in sorted(buckets.items())]
    total = sum(b for b in buckets.values())
    return jsonify({"total": total, "entries": entries})


@bp.get("/groups/statistics/labels")
@login_required
def label_stats():
    group = current_group()
    labels = db.session.query(Label).filter_by(group_id=group.id).all()
    return jsonify(
        [
            {
                "id": lbl.id,
                "name": lbl.name,
                "total": sum((i.purchase_price or 0) * (i.quantity or 1)
                             for i in lbl.items),
            }
            for lbl in labels
        ]
    )


@bp.get("/groups/statistics/locations")
@login_required
def location_stats():
    group = current_group()
    locs = db.session.query(Location).filter_by(group_id=group.id).all()
    return jsonify(
        [
            {
                "id": loc.id,
                "name": loc.name,
                "total": sum((i.purchase_price or 0) * (i.quantity or 1)
                             for i in loc.items),
            }
            for loc in locs
        ]
    )
