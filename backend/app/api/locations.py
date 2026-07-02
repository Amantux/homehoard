from flask import Blueprint, request, jsonify, abort

from ..extensions import db
from ..models import Location
from ..auth import login_required, current_group
from ..schemas.serializers import location_out, location_summary, location_tree

bp = Blueprint("locations", __name__)


def _get(location_id):
    loc = db.session.get(Location, location_id)
    if not loc or loc.group_id != current_group().id:
        abort(404)
    return loc


@bp.get("/locations")
@login_required
def list_locations():
    filter_children = request.args.get("filterChildren", "false").lower() == "true"
    q = db.session.query(Location).filter_by(group_id=current_group().id)
    locs = q.all()
    if filter_children:
        locs = [l for l in locs if l.parent_id is None]
    return jsonify([location_out(l, with_items=False) for l in locs])


@bp.get("/locations/tree")
@login_required
def tree():
    roots = (
        db.session.query(Location)
        .filter_by(group_id=current_group().id, parent_id=None)
        .all()
    )
    return jsonify([location_tree(r) for r in roots])


@bp.post("/locations")
@login_required
def create_location():
    data = request.get_json(force=True) or {}
    loc = Location(
        name=data.get("name", ""),
        description=data.get("description", ""),
        parent_id=data.get("parentId"),
        group_id=current_group().id,
    )
    db.session.add(loc)
    db.session.commit()
    return jsonify(location_out(loc)), 201


@bp.get("/locations/<location_id>")
@login_required
def get_location(location_id):
    return jsonify(location_out(_get(location_id)))


@bp.put("/locations/<location_id>")
@login_required
def update_location(location_id):
    loc = _get(location_id)
    data = request.get_json(force=True) or {}
    if "name" in data:
        loc.name = data["name"]
    if "description" in data:
        loc.description = data["description"]
    if "parentId" in data:
        loc.parent_id = data["parentId"] or None
    db.session.commit()
    return jsonify(location_out(loc))


@bp.delete("/locations/<location_id>")
@login_required
def delete_location(location_id):
    loc = _get(location_id)
    db.session.delete(loc)
    db.session.commit()
    return "", 204
