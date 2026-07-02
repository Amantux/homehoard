from datetime import datetime

from flask import Blueprint, request, jsonify, abort

from ..extensions import db
from ..models import Item, ItemField, Label, Location, Bin
from ..auth import login_required, current_group
from ..schemas.serializers import item_out, item_summary, location_summary

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
    page = int(args.get("page", 1) or 1)
    per_page = int(args.get("pageSize", 50) or 50)
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
