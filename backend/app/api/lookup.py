"""Inventory-only code lookup and a 'where is it' search (items + bins + locations).

No outbound network calls: a scanned code is only ever checked against your own
inventory.
"""
from flask import Blueprint, request, jsonify
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models import Item, Bin, Location, QrTag, Label
from ..auth import login_required, current_group
from ..schemas.serializers import item_summary, item_out, bin_out, location_out
from ..services import resolve
from ..services import vault

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
    """Is this scanned code in inventory? A registered QR/asset tag resolves to its
    target; a product barcode already on an item returns that item. Inventory-only
    (no network) — external product identification is /items/identify/<code>."""
    gid = current_group().id
    tag = (
        db.session.query(QrTag)
        .filter(QrTag.group_id == gid,
                db.or_(QrTag.token == code, QrTag.code == code))
        .first()
    )
    if not tag or tag.target is None:
        # An item already carrying this product barcode? (Duplicates are allowed —
        # two identical items share a UPC — so resolve deterministically: oldest first.)
        item = (vault.visible(db.session.query(Item))
                .filter_by(group_id=gid, barcode=code)
                .order_by(Item.created_at.asc(), Item.id.asc()).first())
        if item:
            return jsonify({"status": "item", "targetId": item.id,
                            "target": item_summary(item)})
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


# Ranking happens in Python, so the SQL fetch is capped rather than unbounded:
# without a ceiling an empty query would load the whole inventory just to sort
# rows that all tie at zero. The pool is far larger than any limit a caller
# asks for, so the top matches are still found — we just stop reading at a sane
# depth on huge inventories.
_RANK_POOL = 500


def _rank(rows, q, limit):
    """Order matches by relevance and record WHY each matched.

    The filter above already accepts a row that matched only on a label or in
    the description, but ordering by name alone threw that signal away — an
    exact name hit sorted no better than an incidental description mention. The
    shared scorer restores it, and ``matchedOn`` lets a caller explain the
    choice ("matched on label: power tools").
    """
    ranked = resolve.rank(rows, q)
    out = []
    for row, _score, matched_on in ranked[:limit]:
        row["matchedOn"] = matched_on
        out.append(row)
    return out


def _token_stems(q: str) -> list[list[str]]:
    """Per word of the query, the LIKE-able variants that should count as a hit.

    Written after a 46-item persona run showed the most HUMAN queries failing
    against a single contiguous LIKE: 'battery' missed "batteries", the words of
    'screwdriver phillips' had to be adjacent and ordered, 'dewalt drill' missed
    a name where brand and noun sit apart. Tokenising gives AND-of-words in any
    order; the crude suffix-stem (strip a plural 's', then a trailing 'y' so
    battery/batteries share the stem 'batter') covers singular/plural and the
    trailing-s typo without a stemming library — household names, not corpora.
    """
    groups = []
    for tok in q.split():
        variants = {tok}
        if len(tok) > 3 and tok.endswith("s"):
            variants.add(tok[:-1])
        base = tok[:-1] if tok.endswith("s") else tok
        if len(base) > 3 and base.endswith("y"):
            variants.add(base[:-1])
        groups.append(sorted(variants))
    return groups


def _word_filter(columns, q):
    """AND across the query's words, OR across each word's variants+columns."""
    conds = []
    for variants in _token_stems(q):
        ors = []
        for v in variants:
            like = f"%{v}%"
            ors.extend(col.ilike(like) for col in columns)
        conds.append(db.or_(*ors))
    return db.and_(*conds)


def _search_items(gid, q, limit):
    query = vault.visible(db.session.query(Item).filter_by(group_id=gid))
    if q:
        # Every WORD must match somewhere (any order, any column); each word
        # also matches its crude stem so battery/batteries/batterys agree.
        cols = [Item.name, Item.description, Item.search_text, Item.manufacturer,
                Item.model_number, Item.serial_number, Item.barcode, Item.notes]
        conds = []
        for variants in _token_stems(q):
            ors = []
            for v in variants:
                like = f"%{v}%"
                ors.extend(col.ilike(like) for col in cols)
                ors.append(Item.labels.any(Label.name.ilike(like)))
            conds.append(db.or_(*ors))
        query = query.filter(db.and_(*conds))
    rows = [
        {
            "type": "item",
            "id": i.id,
            "name": i.name,
            "where": item_where(i),
            "quantity": i.quantity,
            # Ranking + disambiguation metadata: what a user needs to tell two
            # similarly-named things apart.
            "labels": [lbl.name for lbl in i.labels],
            "description": i.description or "",
            "notes": i.notes or "",
            "imageId": next((a.document_id for a in i.attachments if a.primary), None),
        }
        for i in query.options(
            selectinload(Item.attachments),
            selectinload(Item.labels),
            selectinload(Item.location),
            selectinload(Item.bin).selectinload(Bin.location),
            selectinload(Item.bin).selectinload(Bin.attachments),
        ).order_by(Item.name.asc()).limit(_RANK_POOL).all()
    ]
    return _rank(rows, q, limit)


def _search_bins(gid, q, limit):
    query = db.session.query(Bin).filter_by(group_id=gid)
    if q:
        query = query.filter(_word_filter([Bin.name, Bin.description], q))
    rows = [
        {
            "type": "bin",
            "id": b.id,
            "name": b.name,
            "where": location_path_str(b.location) if b.location else "",
            "count": len(b.items),
            "description": b.description or "",
        }
        for b in query.order_by(Bin.name.asc()).limit(_RANK_POOL).all()
    ]
    return _rank(rows, q, limit)


def _search_locations(gid, q, limit):
    query = db.session.query(Location).filter_by(group_id=gid)
    if q:
        query = query.filter(_word_filter([Location.name, Location.description], q))
    rows = [
        {
            "type": "location",
            "id": loc.id,
            "name": loc.name,
            "where": location_path_str(loc.parent) if loc.parent else "",
            "count": len(loc.items),
            "description": loc.description or "",
        }
        for loc in query.order_by(Location.name.asc()).limit(_RANK_POOL).all()
    ]
    return _rank(rows, q, limit)


@bp.get("/search")
@login_required
def search():
    """Find items, bins, and locations and where they are."""
    q = (request.args.get("q") or "").strip()
    # Bound it defensively: a non-numeric ?limit 500'd, and a negative limit
    # slices ranked[:-n] and silently drops the BEST matches.
    try:
        limit = int(request.args.get("limit", 25) or 25)
    except (TypeError, ValueError):
        limit = 25
    limit = max(1, min(limit, 100))
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


@bp.get("/resolve")
@login_required
def resolve_one():
    """Resolve a name/id to ONE thing, or to the candidates worth asking about.

    The single source of truth for "did the user mean this item?", shared by the
    MCP server and the Home Assistant integration (both separate processes, so
    they consume it over HTTP rather than importing the helper). That is what
    keeps a name resolving the same way by voice, by service call, and in chat.

    ``?q=`` the name/id, ``?type=`` item (default), bin, or location.

    ``{"confidence": "high", "match": {...}, "matchedOn": ...}`` — safe to act.
    ``{"confidence": "low", "candidates": [...]}``  — ask which; do NOT act.
    ``{"confidence": "none"}`` — nothing matched.
    """
    q = (request.args.get("q") or "").strip()
    kind = (request.args.get("type") or "item").strip().lower()
    if kind not in ("item", "bin", "location"):
        return jsonify({"confidence": "none", "candidates": [],
                        "error": f"Unknown type '{kind}'."}), 400
    if not q:
        return jsonify({"confidence": "none", "candidates": [],
                        "error": "No name or id given."}), 400
    gid = current_group().id

    # An id is an unambiguous handle — never a fuzzy match.
    model = {"item": Item, "bin": Bin, "location": Location}[kind]
    direct = db.session.get(model, q)
    if direct is not None and direct.group_id == gid:
        return jsonify({"confidence": "high", "matchedOn": "id",
                        "match": _resolved_out(kind, direct)})

    finder = {"item": _search_items, "bin": _search_bins,
              "location": _search_locations}[kind]
    decision = resolve.decide(finder(gid, q, 100), q)
    if decision["confidence"] == "high":
        row = decision["match"]
        obj = db.session.get(model, row["id"])
        return jsonify({"confidence": "high",
                        "matchedOn": decision.get("matchedOn"),
                        "match": _resolved_out(kind, obj)})
    return jsonify(decision)


def _resolved_out(kind: str, obj):
    """Full detail for a confident hit, so callers skip a follow-up GET."""
    if kind == "item":
        return item_out(obj)
    return bin_out(obj) if kind == "bin" else location_out(obj)
