"""Home-inventory report: a valuation + insurance summary over the household's
items, using the value / insured / warranty data already on each item.

`GET /reports/inventory`      — structured report (summary + breakdowns + items).
`GET /reports/inventory.csv`  — the item rows as CSV (for a spreadsheet / insurer).

Read-only and group-scoped. Value is the DOCUMENTED value (purchase price ×
quantity) — the data we actually hold; no depreciation/replacement is invented.
"""
import csv
import io
from datetime import datetime, timedelta

from flask import Blueprint, Response, jsonify
from sqlalchemy.orm import selectinload

from ..auth import current_group, login_required
from ..extensions import db
from ..models import Item
from ..schemas.serializers import iso
from ..services.csv_io import _csv_safe
from ..services import money

bp = Blueprint("reports", __name__)

_EXPIRING_SOON_DAYS = 60


def _value(i) -> float:
    return money.out(money.line_total(i.purchase_price, i.quantity))


def _warranty_status(i, now) -> str:
    """One of: lifetime, active, expiring, expired, none."""
    if i.lifetime_warranty:
        return "lifetime"
    if not i.warranty_expires:
        return "none"
    if i.warranty_expires < now:
        return "expired"
    if i.warranty_expires < now + timedelta(days=_EXPIRING_SOON_DAYS):
        return "expiring"
    return "active"


def _items(gid):
    # Eager-load what _row() touches (location, labels, attachments) so the whole-
    # inventory report is a handful of queries, not N+1 across every item.
    return (db.session.query(Item)
            .filter_by(group_id=gid, archived=False)
            .options(selectinload(Item.location),
                     selectinload(Item.labels),
                     selectinload(Item.attachments))
            .all())


def _row(i, now):
    return {
        "id": i.id,
        "name": i.name,
        "location": i.location.name if i.location else "",
        "labels": [lbl.name for lbl in i.labels],
        "serialNumber": i.serial_number or "",
        "purchaseFrom": i.purchase_from or "",
        "purchaseDate": iso(i.purchase_date),
        "purchasePrice": money.out(i.purchase_price) or 0,
        "quantity": i.quantity or 1,
        "lineValue": _value(i),
        "insured": bool(i.insured),
        "warrantyStatus": _warranty_status(i, now),
        "imageId": next((a.document_id for a in i.attachments if a.primary), None),
    }


@bp.get("/reports/inventory")
@login_required
def inventory_report():
    group = current_group()
    now = datetime.utcnow()  # naive UTC, matches how dates are stored
    items = _items(group.id)
    rows = [_row(i, now) for i in items]

    total_value = round(sum(r["lineValue"] for r in rows), 2)
    insured_value = round(sum(r["lineValue"] for r in rows if r["insured"]), 2)
    warranty = {"lifetime": 0, "active": 0, "expiring": 0, "expired": 0, "none": 0}
    for r in rows:
        warranty[r["warrantyStatus"]] += 1

    def _by(attr_name):
        agg = {}
        for i in items:
            objs = i.labels if attr_name == "labels" else (
                [i.location] if i.location else [])
            for o in objs:
                if o is None:
                    continue
                b = agg.setdefault(o.id, {"name": o.name, "count": 0, "value": 0.0})
                b["count"] += 1
                b["value"] = round(b["value"] + _value(i), 2)
        return sorted(agg.values(), key=lambda b: b["value"], reverse=True)

    return jsonify({
        "generatedAt": iso(now),
        "currency": group.currency,
        "summary": {
            "totalItems": len(rows),
            "totalValue": total_value,
            "insuredValue": insured_value,
            "uninsuredValue": round(total_value - insured_value, 2),
            "insuredCount": sum(1 for r in rows if r["insured"]),
            "warranty": warranty,
        },
        "byLocation": _by("location"),
        "byLabel": _by("labels"),
        "items": sorted(rows, key=lambda r: r["lineValue"], reverse=True),
    })


@bp.get("/reports/inventory.csv")
@login_required
def inventory_report_csv():
    now = datetime.utcnow()  # naive UTC, matches how dates are stored
    rows = [_row(i, now) for i in _items(current_group().id)]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Location", "Labels", "Serial", "Purchased from",
                "Purchase date", "Purchase price", "Quantity", "Line value",
                "Insured", "Warranty"])
    for r in sorted(rows, key=lambda r: r["lineValue"], reverse=True):
        # Neutralize spreadsheet formula injection on the free-text cells (CWE-1236).
        w.writerow([_csv_safe(r["name"]), _csv_safe(r["location"]),
                    _csv_safe("; ".join(r["labels"])), _csv_safe(r["serialNumber"]),
                    _csv_safe(r["purchaseFrom"]), r["purchaseDate"] or "",
                    r["purchasePrice"], r["quantity"], r["lineValue"],
                    "yes" if r["insured"] else "no", r["warrantyStatus"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":
                             'attachment; filename="homehoard-inventory-report.csv"'})
