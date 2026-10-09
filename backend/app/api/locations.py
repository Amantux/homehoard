from flask import Blueprint, request, jsonify
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models import Location, Bin
from ..auth import login_required, current_group
from ._scoping import get_owned_or_404
from ._validation import list_limit
from ..schemas.serializers import location_out, location_tree

bp = Blueprint("locations", __name__)


def _get(location_id):
    loc = get_owned_or_404(Location, location_id)
    return loc


def _validate_parent(parent_id, moving=None):
    """Return (parent_id_or_None, error_or_None) for a proposed parent.

    Rejects a parent in another group, a location as its own parent, and any
    parent that sits below ``moving`` (which would create a cycle / orphan the
    subtree from the tree roots).
    """
    if not parent_id:
        return None, None
    parent = db.session.get(Location, parent_id)
    if not parent or parent.group_id != current_group().id:
        return None, "Unknown parent location."
    if moving is not None:
        node, seen = parent, set()
        while node is not None and node.id not in seen:
            if node.id == moving.id:
                return None, "Can't move a location inside one of its own sub-locations."
            seen.add(node.id)
            node = node.parent
    return parent_id, None


@bp.get("/locations")
@login_required
def list_locations():
    """Locations in this group (bare array). ``?filterChildren=true`` keeps
    top-level only; ``?limit=`` caps the result (1..1000, default 1000;
    non-integer → 400)."""
    filter_children = request.args.get("filterChildren", "false").lower() == "true"
    # Eager-load the collections location_out counts/lists so a list of N
    # locations stays a handful of queries, not ~4N lazy loads.
    q = (
        db.session.query(Location)
        .filter_by(group_id=current_group().id)
        .options(
            selectinload(Location.items),
            selectinload(Location.children),
            selectinload(Location.bins).selectinload(Bin.items),
        )
    )
    # Filter in SQL (was a post-query list filter) so ?limit applies to the
    # rows actually returned.
    if filter_children:
        q = q.filter(Location.parent_id.is_(None))
    locs = q.order_by(Location.name, Location.id).limit(list_limit()).all()
    return jsonify([location_out(loc, with_items=False) for loc in locs])


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
    parent_id, error = _validate_parent(data.get("parentId"))
    if error:
        return jsonify({"error": error}), 422
    loc = Location(
        name=data.get("name", ""),
        description=data.get("description", ""),
        parent_id=parent_id,
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
        parent_id, error = _validate_parent(data["parentId"], moving=loc)
        if error:
            return jsonify({"error": error}), 422
        loc.parent_id = parent_id
    db.session.commit()
    return jsonify(location_out(loc))


@bp.get("/locations/<location_id>/path")
@login_required
def location_path(location_id):
    """Full ancestor chain (root → this location) for breadcrumbs."""
    loc = _get(location_id)
    chain, node, seen = [], loc, set()
    while node is not None and node.id not in seen:
        seen.add(node.id)
        chain.append({"id": node.id, "name": node.name})
        node = node.parent
    return jsonify(list(reversed(chain)))


@bp.delete("/locations/<location_id>")
@login_required
def delete_location(location_id):
    loc = _get(location_id)
    db.session.delete(loc)
    db.session.commit()
    return "", 204
