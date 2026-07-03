"""Inventory-only code lookup and a 'where is it' search (items + bins + locations).

No outbound network calls: a scanned code is only ever checked against your own
inventory.
"""
from flask import Blueprint, request, jsonify

from ..extensions import db
from ..models import Item, Bin, Location, QrTag, Label
from ..auth import login_required, current_group
from ..schemas.serializers import item_summary, bin_out, location_out

bp = Blueprint("lookup", __name__)


def location_path_str(loc) -> str:
    """Human 'Garage › Tool Shelf' path walking up the location parents."""
    parts, seen = [], set()
    while loc is not None and loc.id not in seen:
        seen.add(loc.id)
        parts.append(loc.name)
        loc = loc.parent
    return " › ".join(reversed(parts))


def item_where(item) -> str:
    if item.bin:
        base = item.bin.name
        loc = location_path_str(item.bin.location) if item.bin.location else ""
        return f"{base} · {loc}" if loc else base
    if item.location:
        return location_path_str(item.location)
    return "Unassigned"


@bp.get("/barcode/<code>")
@login_required
def barcode_lookup(code):
    """Is this scanned code in inventory? If so, return what it is / what's in it."""
    gid = current_group().id
    tag = (
        db.session.query(QrTag)
        .filter(QrTag.group_id == gid,
                db.or_(QrTag.token == code, QrTag.code == code))
        .first()
    )
    if not tag or tag.target is None:
        return jsonify({"status": "not_found", "code": code})

    # For a bin or location, "what's in it" comes back with the full contents.
    if tag.kind == "item":
        target = item_summary(tag.target)
    elif tag.kind == "bin":
        target = bin_out(tag.target)
    else:
        target = location_out(tag.target)
    return jsonify(
        {"status": "registered", "kind": tag.kind, "targetId": tag.target_id,
         "target": target}
    )


def _search_items(gid, q, limit):
    query = db.session.query(Item).filter_by(group_id=gid)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Item.name.ilike(like),
                Item.description.ilike(like),
                Item.manufacturer.ilike(like),
                Item.model_number.ilike(like),
                Item.serial_number.ilike(like),
                Item.notes.ilike(like),
                Item.labels.any(Label.name.ilike(like)),
            )
        )
    return [
        {
            "type": "item",
            "id": i.id,
            "name": i.name,
            "where": item_where(i),
            "quantity": i.quantity,
            "imageId": next((a.document_id for a in i.attachments if a.primary), None),
        }
        for i in query.order_by(Item.name.asc()).limit(limit).all()
    ]


def _search_bins(gid, q, limit):
    query = db.session.query(Bin).filter_by(group_id=gid)
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Bin.name.ilike(like), Bin.description.ilike(like)))
    return [
        {
            "type": "bin",
            "id": b.id,
            "name": b.name,
            "where": location_path_str(b.location) if b.location else "",
            "count": len(b.items),
        }
        for b in query.order_by(Bin.name.asc()).limit(limit).all()
    ]


def _search_locations(gid, q, limit):
    query = db.session.query(Location).filter_by(group_id=gid)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(Location.name.ilike(like), Location.description.ilike(like))
        )
    return [
        {
            "type": "location",
            "id": loc.id,
            "name": loc.name,
            "where": location_path_str(loc.parent) if loc.parent else "",
            "count": len(loc.items),
        }
        for loc in query.order_by(Location.name.asc()).limit(limit).all()
    ]


@bp.get("/search")
@login_required
def search():
    """Find items, bins, and locations and where they are."""
    q = (request.args.get("q") or "").strip()
    limit = min(int(request.args.get("limit", 25) or 25), 100)
    gid = current_group().id

    types = request.args.get("types", "item,bin,location").split(",")
    results = []
    if "item" in types:
        results += _search_items(gid, q, limit)
    if "bin" in types:
        results += _search_bins(gid, q, limit)
    if "location" in types:
        results += _search_locations(gid, q, limit)
    return jsonify({"results": results, "total": len(results)})
