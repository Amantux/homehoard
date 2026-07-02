"""Miscellaneous endpoints: status, currency, qrcode, actions, reporting, import/export."""
import io

from flask import Blueprint, request, jsonify, Response, send_file

from ..extensions import db
from ..models import Item
from ..auth import login_required, current_group
from ..services.csv_io import export_items, import_items
from ..schemas.serializers import _fmt_asset

bp = Blueprint("misc", __name__)

CURRENCIES = [
    {"code": "usd", "name": "United States Dollar", "symbol": "$", "local": "en-US"},
    {"code": "eur", "name": "Euro", "symbol": "€", "local": "de-DE"},
    {"code": "gbp", "name": "British Pound", "symbol": "£", "local": "en-GB"},
    {"code": "jpy", "name": "Japanese Yen", "symbol": "¥", "local": "ja-JP"},
    {"code": "cad", "name": "Canadian Dollar", "symbol": "$", "local": "en-CA"},
    {"code": "aud", "name": "Australian Dollar", "symbol": "$", "local": "en-AU"},
    {"code": "chf", "name": "Swiss Franc", "symbol": "Fr", "local": "de-CH"},
    {"code": "inr", "name": "Indian Rupee", "symbol": "₹", "local": "en-IN"},
    {"code": "sek", "name": "Swedish Krona", "symbol": "kr", "local": "sv-SE"},
]


@bp.get("/status")
def status():
    return jsonify(
        {
            "health": True,
            "versions": ["v1"],
            "title": "Shelfie",
            "message": "Shelfie — homebox port running on Flask",
        }
    )


@bp.get("/currency")
def currency():
    return jsonify(CURRENCIES)


@bp.get("/qrcode")
@login_required
def qrcode_gen():
    import qrcode

    data = request.args.get("data", "")
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


# --- Import / Export -----------------------------------------------------
@bp.get("/items/export")
@login_required
def export():
    csv_text = export_items(current_group().id)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=shelfie.csv"},
    )


@bp.post("/items/import")
@login_required
def do_import():
    file = request.files.get("csv") or request.files.get("file")
    if file:
        text = file.read().decode("utf-8-sig")
    else:
        text = (request.get_json(silent=True) or {}).get("data", "")
    if not text:
        return jsonify({"error": "no csv data"}), 422
    count = import_items(current_group().id, text)
    return jsonify({"imported": count}), 201


# --- Reporting -----------------------------------------------------------
@bp.get("/reporting/bill-of-materials")
@login_required
def bill_of_materials():
    csv_text = export_items(current_group().id)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=bom.csv"},
    )


# --- Actions (maintenance/cleanup helpers) -------------------------------
@bp.post("/actions/ensure-asset-ids")
@login_required
def ensure_asset_ids():
    items = (
        db.session.query(Item)
        .filter_by(group_id=current_group().id)
        .order_by(Item.created_at.asc())
        .all()
    )
    next_id = 1
    completed = 0
    used = {i.asset_id for i in items if i.asset_id}
    for i in items:
        if not i.asset_id:
            while next_id in used:
                next_id += 1
            i.asset_id = next_id
            used.add(next_id)
            completed += 1
    db.session.commit()
    return jsonify({"completed": completed})


@bp.post("/actions/ensure-import-refs")
@login_required
def ensure_import_refs():
    import uuid

    items = db.session.query(Item).filter_by(group_id=current_group().id).all()
    completed = 0
    for i in items:
        if not i.import_ref:
            i.import_ref = uuid.uuid4().hex[:8]
            completed += 1
    db.session.commit()
    return jsonify({"completed": completed})


@bp.post("/actions/zero-item-time-fields")
@login_required
def zero_time_fields():
    items = db.session.query(Item).filter_by(group_id=current_group().id).all()
    completed = 0
    for i in items:
        for attr in ("purchase_date", "sold_date", "warranty_expires"):
            val = getattr(i, attr)
            if val and (val.hour or val.minute or val.second):
                setattr(i, attr, val.replace(hour=0, minute=0, second=0, microsecond=0))
                completed += 1
    db.session.commit()
    return jsonify({"completed": completed})


@bp.post("/actions/set-primary-photos")
@login_required
def set_primary_photos():
    items = db.session.query(Item).filter_by(group_id=current_group().id).all()
    completed = 0
    for i in items:
        photos = [a for a in i.attachments if a.type == "photo"]
        if photos and not any(a.primary for a in photos):
            photos[0].primary = True
            completed += 1
    db.session.commit()
    return jsonify({"completed": completed})


# --- Assets --------------------------------------------------------------
@bp.get("/assets/<asset_id>")
@login_required
def get_by_asset(asset_id):
    from ..schemas.serializers import item_summary

    # Accept "000-001" or raw integer
    try:
        if "-" in asset_id:
            hi, lo = asset_id.split("-")
            num = int(hi) * 1000 + int(lo)
        else:
            num = int(asset_id)
    except ValueError:
        return jsonify({"error": "invalid asset id"}), 422
    items = (
        db.session.query(Item)
        .filter_by(group_id=current_group().id, asset_id=num)
        .all()
    )
    return jsonify(
        {"items": [item_summary(i) for i in items], "total": len(items)}
    )
