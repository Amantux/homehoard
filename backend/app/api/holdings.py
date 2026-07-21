"""Per-placement quantities: an item can be stocked in multiple bins/locations.
Holdings are the source of truth; item.quantity (total) + item.location/bin
(primary) are resynced after every change (services/holdings.py). All handlers are
group-scoped (IDOR-safe)."""
from flask import Blueprint, request, jsonify, abort

from ..extensions import db
from ..models import Item, ItemHolding, Bin, Location
from ..auth import login_required, current_group
from ..schemas.serializers import holding_out, item_out
from ..services.holdings import resync_item

bp = Blueprint("holdings", __name__)


def _item(item_id) -> Item:
    it = db.session.get(Item, item_id)
    if not it or it.group_id != current_group().id:
        abort(404)
    return it


def _holding(holding_id) -> ItemHolding:
    h = db.session.get(ItemHolding, holding_id)
    if not h or h.group_id != current_group().id:
        abort(404)
    return h


def _placement(data):
    """Resolve + group-validate a bin/location from the payload. A bin's location
    is inherited. Returns (location_id, bin_id); aborts 404 on a foreign target."""
    gid = current_group().id
    bin_id = data.get("binId") or None
    location_id = data.get("locationId") or None
    if bin_id:
        b = db.session.get(Bin, bin_id)
        if not b or b.group_id != gid:
            abort(404)
        location_id = b.location_id
    elif location_id:
        loc = db.session.get(Location, location_id)
        if not loc or loc.group_id != gid:
            abort(404)
    return location_id, bin_id


def _positive_qty(value):
    try:
        qty = float(value)
    except (TypeError, ValueError):
        return None, (jsonify({"error": "quantity must be a number"}), 422)
    if qty <= 0:
        return None, (jsonify({"error": "quantity must be positive"}), 422)
    return qty, None


@bp.get("/items/<item_id>/holdings")
@login_required
def list_holdings(item_id):
    it = _item(item_id)
    return jsonify([holding_out(h) for h in
                    sorted(it.holdings, key=lambda h: -(h.quantity or 0))])


@bp.post("/items/<item_id>/holdings")
@login_required
def add_holding(item_id):
    it = _item(item_id)
    data = request.get_json(force=True) or {}
    location_id, bin_id = _placement(data)
    qty, err = _positive_qty(data.get("quantity", 1))
    if err:
        return err
    it.holdings.append(ItemHolding(  # append only; cascade persists it
        location_id=location_id, bin_id=bin_id, quantity=qty,
        notes=(data.get("notes") or ""), group_id=it.group_id))
    resync_item(it)
    db.session.commit()
    return jsonify(item_out(it)), 201


@bp.put("/holdings/<holding_id>")
@login_required
def update_holding(holding_id):
    h = _holding(holding_id)
    data = request.get_json(force=True) or {}
    if "binId" in data or "locationId" in data:
        h.location_id, h.bin_id = _placement(data)
    if "quantity" in data:
        qty, err = _positive_qty(data["quantity"])
        if err:
            return err
        h.quantity = qty
    if "notes" in data:
        h.notes = data["notes"] or ""
    resync_item(h.item)
    db.session.commit()
    return jsonify(item_out(h.item))


@bp.delete("/holdings/<holding_id>")
@login_required
def delete_holding(holding_id):
    h = _holding(holding_id)
    item = h.item
    if len(item.holdings) <= 1:
        return jsonify({"error": "an item must have at least one placement"}), 422
    db.session.delete(h)
    item.holdings.remove(h)
    resync_item(item)
    db.session.commit()
    return jsonify(item_out(item))


@bp.post("/holdings/<holding_id>/move")
@login_required
def move_holding(holding_id):
    """Move all or part of a placement's quantity to another bin/location. A full
    move relocates the holding; a partial move splits it, merging into an existing
    holding at the destination if one is there. Total quantity is conserved."""
    h = _holding(holding_id)
    data = request.get_json(force=True) or {}
    dest_loc, dest_bin = _placement({"binId": data.get("toBinId"),
                                     "locationId": data.get("toLocationId")})
    item = h.item
    if dest_loc == h.location_id and dest_bin == h.bin_id:
        return jsonify(item_out(item))  # no-op: already there
    if data.get("quantity") is None:
        amount = h.quantity
    else:
        amount, err = _positive_qty(data["quantity"])
        if err:
            return err
    if amount > h.quantity:
        return jsonify({"error": "can't move more than the placement holds"}), 422

    dest = next((x for x in item.holdings if x.id != h.id
                 and x.location_id == dest_loc and x.bin_id == dest_bin), None)
    if amount >= h.quantity and dest is None:
        h.location_id, h.bin_id = dest_loc, dest_bin      # relocate whole holding
    else:
        h.quantity = round(h.quantity - amount, 4)
        if dest is not None:
            dest.quantity = round(dest.quantity + amount, 4)
        else:
            item.holdings.append(ItemHolding(  # append only; cascade persists it
                location_id=dest_loc, bin_id=dest_bin,
                quantity=amount, group_id=item.group_id))
        if h.quantity <= 0:                               # fully drained into dest
            db.session.delete(h)
            item.holdings.remove(h)
    resync_item(item)
    db.session.commit()
    return jsonify(item_out(item))
