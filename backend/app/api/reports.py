"""Home-inventory report: a valuation + insurance summary over the household's
items, using the value / insured / warranty data already on each item.

`GET /reports/inventory`      — structured report (summary + breakdowns + items).
`GET /reports/inventory.csv`  — the item rows as CSV (for a spreadsheet / insurer).

Read-only and group-scoped. Value is the DOCUMENTED value (purchase price ×
quantity) — the data we actually hold; no depreciation/replacement is invented.
"""
import csv
import io
from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, jsonify
from sqlalchemy.orm import selectinload

from ..auth import current_group, login_required
from ..extensions import db
from ..models import Item
from ..schemas.serializers import iso
from ..schemas.serializers import num
from ..timeutil import as_utc, utcnow
from ..services.csv_io import _csv_safe
from ..services import money
from ..services import vault

bp = Blueprint("reports", __name__)

_EXPIRING_SOON_DAYS = 60
# Sentinel sorting after any real (aware-UTC) due date.
_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)

# Attention tiers, most urgent first.
_SEVERITY_ORDER = {"expired": 0, "expiring": 1, "stale": 2, "incomplete": 3}


def _value(i) -> float:
    return money.out(money.line_total(i.purchase_price, i.quantity))


def _warranty_status(i, now) -> str:
    """One of: lifetime, active, expiring, expired, none."""
    if i.lifetime_warranty:
        return "lifetime"
    if not i.warranty_expires:
        return "none"
    if as_utc(i.warranty_expires) < now:
        return "expired"
    if as_utc(i.warranty_expires) < now + timedelta(days=_EXPIRING_SOON_DAYS):
        return "expiring"
    return "active"


def _items(gid):
    # Eager-load what _row() touches (location, labels, attachments) so the whole-
    # inventory report is a handful of queries, not N+1 across every item.
    return (vault.visible(db.session.query(Item))
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
        "quantity": num(i.quantity) or 1,
        "lineValue": _value(i),
        "insured": bool(i.insured),
        "warrantyStatus": _warranty_status(i, now),
        "imageId": next((a.document_id for a in i.attachments if a.primary), None),
    }


def _attention(i, now):
    """Every reason this item warrants attention, deduplicated, worst first.

    One item can carry more than one reason at once (a lapsed warranty *and* missing
    purchase facts); they come back merged, so the caller emits a single row.
    """
    reasons = []
    status = _warranty_status(i, now)
    if status == "expired":
        exp = as_utc(i.warranty_expires)
        reasons.append({"reason": "warranty_expired", "severity": "expired",
                        "due": exp, "gap": f"warranty expired on {exp.date().isoformat()}"})
    elif status == "expiring":
        exp = as_utc(i.warranty_expires)
        reasons.append({"reason": "warranty_expiring", "severity": "expiring",
                        "due": exp, "gap": f"warranty expires on {exp.date().isoformat()}"})

    if i.checked_out and i.checkout_due and as_utc(i.checkout_due) < now:
        due = as_utc(i.checkout_due)
        reasons.append({"reason": "checkout_overdue", "severity": "stale", "due": due,
                        "gap": f"still out (to {i.checked_out_to or 'unknown person'})"
                               f" past due {due.date().isoformat()}"})

    missing = []
    if not i.purchase_price:
        missing.append("no purchase price")
    if not i.purchase_date:
        missing.append("no purchase date")
    if not i.lifetime_warranty and not i.warranty_expires:
        missing.append("no warranty")
    if missing:
        reasons.append({"reason": "incomplete_key_facts", "severity": "incomplete",
                        "due": None, "gap": "missing " + ", ".join(missing)})

    seen, out = set(), []
    for r in reasons:
        if r["reason"] in seen:
            continue
        seen.add(r["reason"])
        out.append(r)
    return out


def _attention_rows(items, now):
    """One row per item needing attention, severity-ordered then due-date-ordered."""
    rows = []
    for i in items:
        reasons = _attention(i, now)
        if not reasons:
            continue
        top = reasons[0]
        rows.append({
            "id": i.id,
            "name": i.name,
            "severity": top["severity"],
            "reasons": [r["reason"] for r in reasons],
            "gap": top["gap"],
            "due": top["due"],
        })

    def _key(r):
        return (_SEVERITY_ORDER.get(r["severity"], len(_SEVERITY_ORDER)),
                r["due"] is None, r["due"] or _FAR_FUTURE)

    rows.sort(key=_key)
    return rows


@bp.get("/reports/inventory")
@login_required
def inventory_report():
    group = current_group()
    now = utcnow()
    items = _items(group.id)
    rows = [_row(i, now) for i in items]

    total_value = round(sum(r["lineValue"] for r in rows), 2)
    insured_value = round(sum(r["lineValue"] for r in rows if r["insured"]), 2)
    warranty = {"lifetime": 0, "active": 0, "expiring": 0, "expired": 0, "none": 0}
    for r in rows:
        warranty[r["warrantyStatus"]] += 1

    # The attention list: one row per item that needs the household's eye, built
    # from the same items the valuation above covers. Severity first, due date
    # within a level, so the top of the list is the most urgent gap.
    attention = [
        {
            "id": r["id"],
            "name": r["name"],
            "severity": r["severity"],
            "reasons": r["reasons"],
            "gap": r["gap"],
            "due": iso(r["due"]),
        }
        for r in _attention_rows(items, now)
    ]

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
            "attention": attention,
        },
        "byLocation": _by("location"),
        "byLabel": _by("labels"),
        "items": sorted(rows, key=lambda r: r["lineValue"], reverse=True),
    })


@bp.get("/reports/inventory.csv")
@login_required
def inventory_report_csv():
    now = utcnow()
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
