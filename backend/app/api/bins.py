from flask import Blueprint, request, jsonify, abort

from ..extensions import db
from sqlalchemy.orm import selectinload, joinedload

from ..models import Bin, Item
from ..auth import login_required, current_group
from ..schemas.serializers import bin_out, bin_summary, item_summary
from ..services.holdings import resync_item, primary_holding, resync_bin_holdings

bp = Blueprint("bins", __name__)


def _get(bin_id) -> Bin:
    b = db.session.get(Bin, bin_id)
    if not b or b.group_id != current_group().id:
        abort(404)
    return b


@bp.get("/bins")
@login_required
def list_bins():
    q = (db.session.query(Bin).filter_by(group_id=current_group().id)
         .options(selectinload(Bin.holdings), selectinload(Bin.attachments),
                  joinedload(Bin.location)))
    location_id = request.args.get("location")
    if location_id:
        q = q.filter(Bin.location_id == location_id)
    return jsonify([bin_summary(b) | {"itemCount": len(b.holdings)} for b in q.all()])


@bp.post("/bins")
@login_required
def create_bin():
    data = request.get_json(force=True) or {}
    b = Bin(
        name=data.get("name", ""),
        description=data.get("description", ""),
        location_id=data.get("locationId") or None,
        group_id=current_group().id,
    )
    db.session.add(b)
    db.session.commit()
    return jsonify(bin_out(b)), 201


@bp.get("/bins/<bin_id>")
@login_required
def get_bin(bin_id):
    return jsonify(bin_out(_get(bin_id)))


@bp.put("/bins/<bin_id>")
@login_required
def update_bin(bin_id):
    b = _get(bin_id)
    data = request.get_json(force=True) or {}
    if "name" in data:
        b.name = data["name"]
    if "description" in data:
        b.description = data["description"]
    if "locationId" in data:
        b.location_id = data["locationId"] or None
        # Moving a bin carries its contents: every placement in the bin follows
        # it to the new location, and each affected item is resynced.
        resync_bin_holdings(b)
    db.session.commit()
    return jsonify(bin_out(b))


@bp.delete("/bins/<bin_id>")
@login_required
def delete_bin(bin_id):
    b = _get(bin_id)
    # Detach placements (keep the items, in the bin's location) rather than
    # deleting them with the bin. Null bin_id BEFORE delete to avoid an FK break.
    affected = {h.item for h in b.holdings if h.item}
    for h in list(b.holdings):
        h.bin_id = None
    db.session.delete(b)
    db.session.flush()
    for item in affected:
        resync_item(item)
    db.session.commit()
    return "", 204


@bp.put("/bins/<bin_id>/items/<item_id>")
@login_required
def add_item(bin_id, item_id):
    b = _get(bin_id)
    item = db.session.get(Item, item_id)
    if not item or item.group_id != current_group().id:
        abort(404)
    item.bin_id = b.id
    # An item in a bin inherits the bin's location for consistency.
    if b.location_id:
        item.location_id = b.location_id
    ph = primary_holding(item)  # move the item's primary placement into the bin
    if ph:
        ph.bin_id = item.bin_id
        ph.location_id = item.location_id
    resync_item(item)
    db.session.commit()
    return jsonify(item_summary(item))


@bp.delete("/bins/<bin_id>/items/<item_id>")
@login_required
def remove_item(bin_id, item_id):
    _get(bin_id)
    item = db.session.get(Item, item_id)
    if not item or item.bin_id != bin_id:
        abort(404)
    item.bin_id = None
    ph = primary_holding(item)  # pull the primary placement out of the bin
    if ph and ph.bin_id == bin_id:
        ph.bin_id = None
    resync_item(item)
    db.session.commit()
    return "", 204
