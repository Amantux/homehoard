"""Barcode product lookup and a 'where is it' search."""
from flask import Blueprint, request, jsonify

from ..extensions import db
from ..models import Item, QrTag, Label
from ..auth import login_required, current_group
from ..schemas.serializers import item_summary, bin_summary, location_summary
from ..services.barcode import lookup_product

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
    """Resolve a barcode: first to a registered record, else to product info."""
    gid = current_group().id
    tag = (
        db.session.query(QrTag)
        .filter(QrTag.group_id == gid,
                db.or_(QrTag.token == code, QrTag.code == code))
        .first()
    )
    if tag:
        target = tag.target
        if tag.kind == "item" and target:
            summary = item_summary(target)
        elif tag.kind == "bin" and target:
            summary = bin_summary(target)
        elif tag.kind == "location" and target:
            summary = location_summary(target)
        else:
            summary = None
        return jsonify(
            {"status": "registered", "kind": tag.kind, "targetId": tag.target_id,
             "target": summary}
        )

    product = lookup_product(code)
    return jsonify(
        {"status": "found" if product else "not_found", "code": code,
         "product": product}
    )


@bp.get("/search")
@login_required
def search():
    """Find items and where they are. Returns lightweight results with a path."""
    q = (request.args.get("q") or "").strip()
    limit = min(int(request.args.get("limit", 25) or 25), 100)
    query = db.session.query(Item).filter_by(group_id=current_group().id)
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
    items = query.order_by(Item.name.asc()).limit(limit).all()
    return jsonify(
        {
            "results": [
                {
                    "id": i.id,
                    "name": i.name,
                    "description": i.description,
                    "quantity": i.quantity,
                    "imageId": next(
                        (a.document_id for a in i.attachments if a.primary), None
                    ),
                    "where": item_where(i),
                    "locationId": i.location_id,
                    "binId": i.bin_id,
                }
                for i in items
            ],
            "total": len(items),
        }
    )
