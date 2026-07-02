"""Consolidated read endpoints for the Home Assistant integration.

Two endpoints keep HA polling cheap and power the richer entities:

* ``/api/v1/ha/summary``  – one call with totals + "needs attention" counts.
* ``/api/v1/ha/calendar`` – warranty-expiry and scheduled-maintenance events,
  consumed by the HomeHoard Calendar entity.
"""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from ..extensions import db
from ..models import Item, Bin, Label, Location, MaintenanceEntry
from ..auth import login_required, current_group

bp = Blueprint("ha", __name__)


def _parse(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace("+00:00", ""))
    except ValueError:
        return None


def _active_warranty_items(group_id):
    """Items with a future warranty expiry (excludes lifetime + sold)."""
    return (
        db.session.query(Item)
        .filter(
            Item.group_id == group_id,
            Item.sold_date.is_(None),
            Item.lifetime_warranty.is_(False),
            Item.warranty_expires.isnot(None),
        )
        .all()
    )


def _open_maintenance(group_id):
    return (
        db.session.query(MaintenanceEntry)
        .join(Item, Item.id == MaintenanceEntry.item_id)
        .filter(
            Item.group_id == group_id,
            MaintenanceEntry.completed_date.is_(None),
            MaintenanceEntry.scheduled_date.isnot(None),
        )
        .all()
    )


@bp.get("/ha/summary")
@login_required
def summary():
    gid = current_group().id
    now = datetime.utcnow()
    items = db.session.query(Item).filter_by(group_id=gid).all()

    total_value = sum((i.purchase_price or 0) * (i.quantity or 1) for i in items)
    insured_value = sum(
        (i.purchase_price or 0) * (i.quantity or 1) for i in items if i.insured
    )

    warranty_items = _active_warranty_items(gid)
    exp_30 = [i for i in warranty_items if now <= i.warranty_expires <= now + timedelta(days=30)]
    exp_90 = [i for i in warranty_items if now <= i.warranty_expires <= now + timedelta(days=90)]

    maint = _open_maintenance(gid)
    overdue = [m for m in maint if m.scheduled_date < now]
    upcoming_30 = [m for m in maint if now <= m.scheduled_date <= now + timedelta(days=30)]

    return jsonify(
        {
            "health": True,
            "group": current_group().name,
            "totals": {
                "items": len(items),
                "bins": db.session.query(Bin).filter_by(group_id=gid).count(),
                "locations": db.session.query(Location).filter_by(group_id=gid).count(),
                "labels": db.session.query(Label).filter_by(group_id=gid).count(),
                "value": round(total_value, 2),
                "insuredValue": round(insured_value, 2),
                "withWarranty": sum(
                    1 for i in items if i.lifetime_warranty or i.warranty_expires
                ),
            },
            "warrantiesExpiring": {
                "days30": len(exp_30),
                "days90": len(exp_90),
                "items": [
                    {"id": i.id, "name": i.name,
                     "expires": i.warranty_expires.date().isoformat()}
                    for i in sorted(exp_90, key=lambda x: x.warranty_expires)
                ],
            },
            "maintenance": {
                "overdue": len(overdue),
                "upcoming30": len(upcoming_30),
                "entries": [
                    {
                        "id": m.id, "name": m.name, "itemId": m.item_id,
                        "itemName": m.item.name if m.item else None,
                        "scheduled": m.scheduled_date.date().isoformat(),
                        "overdue": m.scheduled_date < now,
                    }
                    for m in sorted(maint, key=lambda x: x.scheduled_date)
                ],
            },
        }
    )


@bp.get("/ha/calendar")
@login_required
def calendar():
    gid = current_group().id
    start = _parse(request.args.get("start"))
    end = _parse(request.args.get("end"))

    def in_range(d):
        if start and d < start:
            return False
        if end and d > end:
            return False
        return True

    events = []
    for i in _active_warranty_items(gid):
        if in_range(i.warranty_expires):
            day = i.warranty_expires.date()
            events.append(
                {
                    "uid": f"warranty-{i.id}",
                    "summary": f"Warranty expires: {i.name}",
                    "start": day.isoformat(),
                    "end": (day + timedelta(days=1)).isoformat(),
                    "category": "warranty",
                    "itemId": i.id,
                }
            )
    for m in _open_maintenance(gid):
        if in_range(m.scheduled_date):
            day = m.scheduled_date.date()
            events.append(
                {
                    "uid": f"maintenance-{m.id}",
                    "summary": f"Maintenance: {m.name}"
                    + (f" ({m.item.name})" if m.item else ""),
                    "start": day.isoformat(),
                    "end": (day + timedelta(days=1)).isoformat(),
                    "category": "maintenance",
                    "itemId": m.item_id,
                }
            )
    events.sort(key=lambda e: e["start"])
    return jsonify(events)
