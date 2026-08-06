import re
from datetime import datetime

from flask import Blueprint, request, jsonify, abort, current_app
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..extensions import db, limiter
from ..models import Item, ItemField, Label, Location, Bin
from ..auth import login_required, current_group
from ..schemas.serializers import item_out, item_summary
from ..services.holdings import ensure_holding, resync_item, primary_holding
from .lookup import location_path_str
from ..services import money

bp = Blueprint("items", __name__)


def _sync_holdings_from_item_form(item, data):
    """Reflect item-form edits to location/bin/quantity into the holdings, then
    resync the denormalized total + primary. Single-placement items stay fully
    editable via the item form; with multiple placements the holdings own the
    quantity (edit them via the placements UI), so a form quantity is ignored."""
    if not item.holdings:
        ensure_holding(item)
        return
    if "locationId" in data or "binId" in data:
        primary = primary_holding(item)
        if primary:
            primary.location_id = item.location_id
            primary.bin_id = item.bin_id
    if "quantity" in data and len(item.holdings) == 1:
        item.holdings[0].quantity = data["quantity"]
    resync_item(item)


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


def _require_owned(model, obj_id, gid):
    """Return obj_id only if it names a row in this group; else 404. Guards against
    binding an item to another household's location / bin / parent item (IDOR): the
    FK alone would accept a cross-group id and item_out would then leak its name."""
    if not obj_id:
        return None
    row = db.session.get(model, obj_id)
    if row is None or row.group_id != gid:
        abort(404)
    return obj_id


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
        "barcode": "barcode",
        "purchasePrice": "purchase_price",
        "purchaseFrom": "purchase_from",
        "soldPrice": "sold_price",
        "soldTo": "sold_to",
        "soldNotes": "sold_notes",
        "lifetimeWarranty": "lifetime_warranty",
        "warrantyDetails": "warranty_details",
    }
    # Money fields are quantized to 2dp on the way in rather than assigned raw:
    # a client sending 19.999 (or "19.99") should be stored as a clean Decimal,
    # not whatever the driver makes of it.
    _MONEY_FIELDS = {"purchase_price", "sold_price"}
    for key, attr in simple.items():
        if key in data and data[key] is not None:
            value = money.to_money(data[key]) if attr in _MONEY_FIELDS else data[key]
            setattr(item, attr, value)
    # barcode is String(64); a pasted 2D/QR value would overflow it on Postgres.
    if item.barcode and len(item.barcode) > 64:
        item.barcode = item.barcode[:64]

    for key, attr in {
        "purchaseDate": "purchase_date",
        "soldDate": "sold_date",
        "warrantyExpires": "warranty_expires",
    }.items():
        if key in data:
            setattr(item, attr, _parse_dt(data[key]))

    gid = item.group_id
    if "locationId" in data:
        item.location_id = _require_owned(Location, data["locationId"], gid)
    if "binId" in data:
        item.bin_id = _require_owned(Bin, data["binId"], gid)
    # An item lives in a bin OR directly in a location. When it's in a bin, its
    # location is inherited from (and kept in sync with) that bin.
    if item.bin_id:
        b = db.session.get(Bin, item.bin_id)  # already ownership-checked above
        if b:  # defensive: a dangling bin_id (no FK enforcement on SQLite) → skip
            item.location_id = b.location_id
    if "parentId" in data:
        item.parent_id = _require_owned(Item, data["parentId"], gid)

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
        q = q.filter(db.or_(Item.name.ilike(like), Item.description.ilike(like),
                            Item.search_text.ilike(like), Item.barcode.ilike(like)))

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
    # Item.id (unique) as a tie-breaker: order_col alone (e.g. non-unique name) makes
    # paginated OFFSET/LIMIT results non-deterministic — rows can repeat or vanish
    # across pages when sort keys collide.
    q = q.order_by(order_col.desc() if descending else order_col.asc(), Item.id.asc())
    # Eager-load everything item_summary touches, so the list is a constant number of
    # queries instead of N+1 across attachments/holdings/labels/location/bin per row.
    q = q.options(
        selectinload(Item.attachments),
        selectinload(Item.holdings),
        selectinload(Item.labels),
        selectinload(Item.location),
        selectinload(Item.bin).selectinload(Bin.location),
        selectinload(Item.bin).selectinload(Bin.attachments),
    )
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
    gid = current_group().id
    bin_id = _require_owned(Bin, data.get("binId"), gid)
    location_id = _require_owned(Location, data.get("locationId"), gid)
    if bin_id:
        b = db.session.get(Bin, bin_id)  # owned (checked above)
        location_id = b.location_id  # inherit the bin's location
    item = Item(
        name=data.get("name", ""),
        description=data.get("description", ""),
        quantity=data.get("quantity") or 1,
        barcode=(data.get("barcode") or "")[:64],
        group_id=gid,
        location_id=location_id,
        bin_id=bin_id,
    )
    # Allocate the per-group asset id with retry: a bare max()+1 races two concurrent
    # creates to the same value, and the partial unique index rejects the loser. add()
    # happens INSIDE the savepoint so a conflict rolls back cleanly, then we re-read
    # the max and try again.
    for _ in range(8):
        item.asset_id = _next_asset_id(gid)
        try:
            with db.session.begin_nested():
                db.session.add(item)
                db.session.flush()
            break
        except IntegrityError:
            continue
    else:
        abort(409, description="could not allocate an asset id — please retry")
    if data.get("labelIds"):
        item.labels = (
            db.session.query(Label)
            .filter(Label.id.in_(data["labelIds"]), Label.group_id == gid)
            .all()
        )
    ensure_holding(item)  # start with one placement mirroring this location/bin
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
    data = request.get_json(force=True) or {}
    _apply(item, data)
    _sync_holdings_from_item_form(item, data)
    db.session.commit()
    return jsonify(item_out(item))


@bp.patch("/items/<item_id>")
@login_required
def patch_item(item_id):
    item = _get(item_id)
    data = request.get_json(force=True) or {}
    _apply(item, data)
    _sync_holdings_from_item_form(item, data)
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
            Item.search_text.ilike(like),
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


def _describe_fields(item):
    return {"name": item.name, "manufacturer": item.manufacturer,
            "model_number": item.model_number}


_SEARCH_TEXT_MAX = 600  # keep search_text bounded (LLM/web output is untrusted)


def _apply_description(item, result):
    """Store the web-searched description as search_text (+ keywords), capped."""
    text = result["description"]
    if result.get("keywords"):
        text = f"{text} {' '.join(result['keywords'])}"
    item.search_text = text.strip()[:_SEARCH_TEXT_MAX]


@bp.post("/items/<item_id>/describe")
@limiter.limit("20/minute")
@login_required
def describe_item(item_id):
    """Look the item up online (Ollama web search) and store a short searchable
    description. Returns the description + sources, or 4xx when unavailable."""
    from ..services import enrich

    item = _get(item_id)
    if not enrich.enabled():
        return jsonify({"error": "Web search isn't configured. Set an Ollama search "
                                 "key (HBOX_OLLAMA_SEARCH_KEY)."}), 409
    result = enrich.describe(_describe_fields(item))
    if not result:
        return jsonify({"error": "Couldn't find a description for this item online."}), 422
    _apply_description(item, result)
    db.session.commit()
    return jsonify({"searchText": item.search_text, "description": result["description"],
                    "keywords": result.get("keywords", []),
                    "sources": result.get("sources", [])})


@bp.get("/items/identify/<code>")
@limiter.limit("30/minute")
@login_required
def identify_item(code):
    """Identify an unknown product barcode online (product DB → Open Food Facts →
    Ollama web-search) so the UI can prefill a new item. Returns a suggestion
    {name, brand, barcode, source} or not_found; 409 when barcode lookup is off."""
    from ..services.barcode import identify_barcode

    if not current_app.config.get("BARCODE_LOOKUP"):
        return jsonify({"status": "disabled",
                        "error": "Barcode lookup is off (set HBOX_BARCODE_LOOKUP)."}), 409
    hit = identify_barcode(code)
    if not hit:
        return jsonify({"status": "not_found", "code": code})
    return jsonify({"status": "suggestion", "code": code, "suggestion": hit})
