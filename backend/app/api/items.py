import re
from datetime import datetime

from flask import Blueprint, request, jsonify, abort
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models import Item, ItemField, Label, Location, Bin
from ..auth import login_required, current_group
from ..schemas.serializers import item_out, item_summary
from .lookup import location_path_str

bp = Blueprint("items", __name__)


def _get(item_id) -> Item:
    item = db.session.get(Item, item_id)
    if not item or item.group_id != current_group().id:
        abort(404)
    return item


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _next_asset_id(group_id) -> int:
    top = (
        db.session.query(Item.asset_id)
        .filter_by(group_id=group_id)
        .order_by(Item.asset_id.desc())
        .first()
    )
    return (top[0] if top and top[0] else 0) + 1


def _apply(item: Item, data: dict):
    simple = {
        "name": "name",
        "description": "description",
        "notes": "notes",
        "quantity": "quantity",
        "insured": "insured",
        "archived": "archived",
        "syncChildLocations": "sync_child_locations",
        "serialNumber": "serial_number",
        "modelNumber": "model_number",
        "manufacturer": "manufacturer",
        "purchasePrice": "purchase_price",
        "purchaseFrom": "purchase_from",
        "soldPrice": "sold_price",
        "soldTo": "sold_to",
        "soldNotes": "sold_notes",
        "lifetimeWarranty": "lifetime_warranty",
        "warrantyDetails": "warranty_details",
    }
    for key, attr in simple.items():
        if key in data and data[key] is not None:
            setattr(item, attr, data[key])

    for key, attr in {
        "purchaseDate": "purchase_date",
        "soldDate": "sold_date",
        "warrantyExpires": "warranty_expires",
    }.items():
        if key in data:
            setattr(item, attr, _parse_dt(data[key]))

    if "locationId" in data:
        item.location_id = data["locationId"] or None
    if "binId" in data:
        item.bin_id = data["binId"] or None
    # An item lives in a bin OR directly in a location. When it's in a bin, its
    # location is inherited from (and kept in sync with) that bin.
    if item.bin_id:
        b = db.session.get(Bin, item.bin_id)
        if b and b.group_id == item.group_id:
            item.location_id = b.location_id
    if "parentId" in data:
        item.parent_id = data["parentId"] or None

    if "labelIds" in data:
        labels = (
            db.session.query(Label)
            .filter(Label.id.in_(data["labelIds"] or []),
                    Label.group_id == item.group_id)
            .all()
        )
        item.labels = labels

    if "fields" in data:
        item.fields.clear()
        for f in data["fields"] or []:
            item.fields.append(
                ItemField(
                    name=f.get("name", ""),
                    type=f.get("type", "text"),
                    text_value=f.get("textValue", ""),
                    number_value=f.get("numberValue", 0) or 0,
                    boolean_value=f.get("booleanValue", False),
                    time_value=_parse_dt(f.get("timeValue")),
                )
            )


@bp.get("/items")
@login_required
def list_items():
    args = request.args
    def _int(name, default):
        try:
            return int(args.get(name, default) or default)
        except (TypeError, ValueError):
            return default

    page = max(1, _int("page", 1))
    # Clamp page size: never unbounded (pageSize<=0 would dump the whole table
    # → memory DoS / excessive data exposure). Upper bound covers the internal
    # "load many for a picker" callers without allowing an attacker to ask for
    # millions of rows. Non-numeric input falls back to the default (no 500).
    per_page = min(max(1, _int("pageSize", 50)), 1000)
    q = db.session.query(Item).filter_by(group_id=current_group().id)

    search = args.get("q")
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(Item.name.ilike(like), Item.description.ilike(like)))

    location_ids = args.getlist("locations")
    if location_ids:
        q = q.filter(Item.location_id.in_(location_ids))

    bin_ids = args.getlist("bins")
    if bin_ids:
        q = q.filter(Item.bin_id.in_(bin_ids))

    label_ids = args.getlist("labels")
    if label_ids:
        negate = args.get("negateTags", "false").lower() == "true"
        if negate:
            q = q.filter(~Item.labels.any(Label.id.in_(label_ids)))
        else:
            q = q.filter(Item.labels.any(Label.id.in_(label_ids)))

    if args.get("includeArchived", "false").lower() != "true":
        q = q.filter(Item.archived.is_(False))

    total = q.count()

    order_col = {
        "name": Item.name,
        "createdAt": Item.created_at,
        "updatedAt": Item.updated_at,
        "purchasePrice": Item.purchase_price,
        "assetId": Item.asset_id,
    }.get(args.get("orderBy", "name"), Item.name)
    descending = args.get("order", "asc").lower() == "desc" or (
        args.get("orderBy") in ("createdAt", "updatedAt")
        and "order" not in args
    )
    q = q.order_by(order_col.desc() if descending else order_col.asc())
    if per_page > 0:
        q = q.offset((page - 1) * per_page).limit(per_page)
    items = q.all()
    return jsonify(
        {
            "items": [item_summary(i) for i in items],
            "page": page,
            "pageSize": per_page,
            "total": total,
        }
    )


@bp.post("/items")
@login_required
def create_item():
    data = request.get_json(force=True) or {}
    bin_id = data.get("binId") or None
    location_id = data.get("locationId") or None
    if bin_id:
        b = db.session.get(Bin, bin_id)
        if b and b.group_id == current_group().id:
            location_id = b.location_id  # inherit the bin's location
    item = Item(
        name=data.get("name", ""),
        description=data.get("description", ""),
        quantity=data.get("quantity") or 1,
        group_id=current_group().id,
        location_id=location_id,
        bin_id=bin_id,
        asset_id=_next_asset_id(current_group().id),
    )
    if data.get("labelIds"):
        item.labels = (
            db.session.query(Label)
            .filter(Label.id.in_(data["labelIds"]),
                    Label.group_id == current_group().id)
            .all()
        )
    db.session.add(item)
    db.session.commit()
    return jsonify(item_out(item)), 201


@bp.get("/items/<item_id>")
@login_required
def get_item(item_id):
    return jsonify(item_out(_get(item_id)))


@bp.put("/items/<item_id>")
@login_required
def update_item(item_id):
    item = _get(item_id)
    _apply(item, request.get_json(force=True) or {})
    db.session.commit()
    return jsonify(item_out(item))


@bp.patch("/items/<item_id>")
@login_required
def patch_item(item_id):
    item = _get(item_id)
    _apply(item, request.get_json(force=True) or {})
    db.session.commit()
    return jsonify(item_out(item))


@bp.delete("/items/<item_id>")
@login_required
def delete_item(item_id):
    db.session.delete(_get(item_id))
    db.session.commit()
    return "", 204


@bp.get("/items/<item_id>/path")
@login_required
def item_path(item_id):
    """Breadcrumb path from root location down to the item."""
    item = _get(item_id)
    path = []
    loc = item.location
    chain = []
    while loc is not None:
        chain.append({"id": loc.id, "name": loc.name, "type": "location"})
        loc = loc.parent
    path.extend(reversed(chain))
    path.append({"id": item.id, "name": item.name, "type": "item"})
    return jsonify(path)


def _placement_of(item):
    """Where an item currently lives, as a ('bin'|'location', id, name, where)
    tuple — or None if it's unplaced."""
    if item.bin_id and item.bin:
        loc = location_path_str(item.bin.location) if item.bin.location else ""
        return ("bin", item.bin_id, item.bin.name, loc)
    if item.location_id and item.location:
        loc = location_path_str(item.location.parent) if item.location.parent else ""
        return ("location", item.location_id, item.location.name, loc)
    return None


def _popular_placements(gid, limit):
    """Fallback when nothing similar is found: the most-populated places.

    Item counts are eager-loaded (one query per collection, not per row), and
    the ancestor path is only walked for the top-N that are actually returned.
    """
    bins = (
        db.session.query(Bin)
        .options(selectinload(Bin.items))
        .filter_by(group_id=gid)
        .all()
    )
    locs = (
        db.session.query(Location)
        .options(selectinload(Location.items))
        .filter_by(group_id=gid)
        .all()
    )
    scored = [("bin", b, len(b.items)) for b in bins if b.items]
    scored += [("location", loc, len(loc.items)) for loc in locs if loc.items]
    scored.sort(key=lambda t: t[2], reverse=True)

    out = []
    for kind, obj, count in scored[:limit]:
        where = (
            location_path_str(obj.location) if kind == "bin" and obj.location
            else location_path_str(obj.parent) if kind == "location" and obj.parent
            else ""
        )
        out.append({"type": kind, "id": obj.id, "name": obj.name, "where": where,
                    "count": count, "samples": [], "basis": "popular"})
    return out


def _placement_suggestions(gid, name, label_ids, exclude_id, limit):
    """Rank places to put an item by where *similar* items already live.

    Similarity = the item name shares a word with an existing item's name,
    description, manufacturer, model, or a label — or they share a label id.
    Falls back to the most-populated places when nothing matches.
    """
    tokens = [t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if len(t) >= 3]
    conds = []
    for t in tokens:
        like = f"%{t}%"
        conds.extend([
            Item.name.ilike(like),
            Item.description.ilike(like),
            Item.manufacturer.ilike(like),
            Item.model_number.ilike(like),
            Item.labels.any(Label.name.ilike(like)),
        ])
    if label_ids:
        conds.append(Item.labels.any(Label.id.in_(label_ids)))

    agg = {}
    if conds:
        q = db.session.query(Item).filter(Item.group_id == gid)
        if exclude_id:
            q = q.filter(Item.id != exclude_id)
        for item in q.filter(db.or_(*conds)).all():
            placement = _placement_of(item)
            if placement is None:
                continue
            kind, pid, pname, where = placement
            entry = agg.setdefault(
                (kind, pid),
                {"type": kind, "id": pid, "name": pname, "where": where,
                 "count": 0, "samples": [], "basis": "similar"},
            )
            entry["count"] += 1
            if len(entry["samples"]) < 3 and item.name not in entry["samples"]:
                entry["samples"].append(item.name)

    results = sorted(agg.values(), key=lambda e: e["count"], reverse=True)[:limit]
    if not results:
        results = _popular_placements(gid, limit)
    return results


@bp.get("/items/suggest-placement")
@login_required
def suggest_placement():
    """Suggest bins/locations to put a (possibly not-yet-created) item, based
    on where similar items already live. Powers the create flow and the HA MCP
    ``suggest_placement`` tool."""
    args = request.args
    label_ids = [x for x in args.get("labels", "").split(",") if x]
    limit = max(1, min(int(args.get("limit", 3) or 3), 10))
    suggestions = _placement_suggestions(
        current_group().id,
        args.get("name", ""),
        label_ids,
        args.get("exclude") or None,
        limit,
    )
    return jsonify({"suggestions": suggestions})


@bp.get("/items/fields")
@login_required
def custom_field_names():
    names = (
        db.session.query(ItemField.name)
        .join(Item, Item.id == ItemField.item_id)
        .filter(Item.group_id == current_group().id)
        .distinct()
        .all()
    )
    return jsonify(sorted({n[0] for n in names}))


@bp.get("/items/fields/values")
@login_required
def custom_field_values():
    field = request.args.get("field")
    q = (
        db.session.query(ItemField.text_value)
        .join(Item, Item.id == ItemField.item_id)
        .filter(Item.group_id == current_group().id)
    )
    if field:
        q = q.filter(ItemField.name == field)
    return jsonify(sorted({v[0] for v in q.distinct().all() if v[0]}))
