"""The report registry: one declarative spec per report the app exposes.

A :class:`ReportSpec` carries a report's whole backend footprint:

- ``id`` — the stable machine id used in URLs (``/api/v1/reports/<id>``).
- ``title`` — the human-facing name (listings, future UIs).
- ``build`` — ``build(db, group_id) -> payload``: turn one group's data into the
  report payload (summary + breakdowns + rows). Valuation, warranty and group
  scoping rules live here, once, per report.
- ``csv_columns`` — optional ordered CSV export headers for the spreadsheet
  export; ``None`` while a report has no export yet.

``REPORTS`` is the ordered registry list. Adding a report means appending a spec;
the blueprint's routes stay thin and delegate to the registered builder.
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, Optional

from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models import Group, Item
from ..schemas.serializers import iso, num
from ..services import money
from ..services import vault
from ..services.alerts import alert_digest
from ..timeutil import as_utc, utcnow

_EXPIRING_SOON_DAYS = 60


@dataclass
class ReportSpec:
    """One report: id, title, payload builder, optional CSV export columns."""

    id: str
    title: str
    build: Callable[..., dict]
    csv_columns: Optional[tuple] = None


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


def _by(attr_name, items):
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


def inventory_payload(db, group_id) -> dict:
    """Build the inventory report payload (summary + breakdowns + items) for one group."""
    group = db.session.get(Group, group_id)
    now = utcnow()
    items = _items(group_id)
    rows = [_row(i, now) for i in items]

    total_value = round(sum(r["lineValue"] for r in rows), 2)
    insured_value = round(sum(r["lineValue"] for r in rows if r["insured"]), 2)
    warranty = {"lifetime": 0, "active": 0, "expiring": 0, "expired": 0, "none": 0}
    for r in rows:
        warranty[r["warrantyStatus"]] += 1

    return {
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
        "byLocation": _by("location", items),
        "byLabel": _by("labels", items),
        "items": sorted(rows, key=lambda r: r["lineValue"], reverse=True),
    }


def digest_payload(db, group_id) -> dict:
    """The attention digest report: what needs attention right now, for one group.

    The digest itself — overdue lends, warranties expiring soon, overdue
    maintenance, consumables running low — is owned by
    :func:`app.services.alerts.alert_digest` and already consumed by the notifier
    dispatch and the HA summary sensor, so this report cannot disagree with them.
    The builder adds the report envelope (``generatedAt`` / ``currency``) and
    nothing else; the alert logic is not copied here.
    """
    group = db.session.get(Group, group_id)
    now = utcnow()
    digest = alert_digest(group_id, now=now)
    return {
        "generatedAt": iso(now),
        "currency": group.currency,
        "isEmpty": digest["isEmpty"],
        "counts": digest["counts"],
        "overdueCheckouts": digest["overdueCheckouts"],
        "warrantyExpiringSoon": digest["warrantyExpiringSoon"],
        "maintenanceOverdue": digest["maintenanceOverdue"],
        "text": digest["text"],
    }


# The key facts a completeness report looks at, in wire order: per-item flag
# plus the per-field missing count it feeds.
_COMPLETENESS_FIELDS = (
    ("hasValue", "Purchase value"),
    ("hasPhoto", "Photo"),
    ("hasLocation", "Location"),
    ("hasLabel", "Label"),
    ("hasWarranty", "Warranty"),
    ("hasPurchaseDate", "Purchase date"),
)


def _completeness(i) -> dict:
    """Which key facts an item carries: hasValue / hasPhoto / hasLocation / ..."""
    return {
        "hasValue": bool(i.purchase_price) and (i.quantity or 0) > 0,
        "hasPhoto": any(a.primary for a in i.attachments),
        "hasLocation": i.location is not None,
        "hasLabel": bool(i.labels),
        "hasWarranty": bool(i.lifetime_warranty or i.warranty_expires),
        "hasPurchaseDate": i.purchase_date is not None,
    }


def completeness_payload(db, group_id) -> dict:
    """The item data-completeness report: per-item flags plus per-field missing counts."""
    group = db.session.get(Group, group_id)
    now = utcnow()
    items = _items(group_id)
    rows = [_row(i, now) for i in items]

    flags = {i.id: _completeness(i) for i in items}
    missing_by_field: dict = {key: [] for key, _label in _COMPLETENESS_FIELDS}
    for i in items:
        for key, _label in _COMPLETENESS_FIELDS:
            if not flags[i.id][key]:
                missing_by_field[key].append(i)

    return {
        "generatedAt": iso(now),
        "currency": group.currency,
        "summary": {
            "totalItems": len(rows),
            "missing": {key: len(missing_by_field[key]) for key, _ in _COMPLETENESS_FIELDS},
        },
        "fields": [
            {
                "key": key,
                "label": label,
                "missing": len(missing_by_field[key]),
                "items": [{"id": i.id, "name": i.name} for i in missing_by_field[key]],
            }
            for key, label in _COMPLETENESS_FIELDS
        ],
        "items": [
            {**r, "missingFields": [k for k, _ in _COMPLETENESS_FIELDS if not flags[r["id"]][k]]}
            for r in rows
            if any(not flags[r["id"]][k] for k, _ in _COMPLETENESS_FIELDS)
        ],
    }


def stale_payload(db, group_id) -> dict:
    """The expiring/stale report: kept items whose warranty is expired or expiring.

    Time-driven half of the attention set: lifetime warranties never go stale,
    and everything past or inside ``_EXPIRING_SOON_DAYS`` of expiring is listed,
    soonest due date first (expired before expiring).
    """
    group = db.session.get(Group, group_id)
    now = utcnow()
    items = _items(group_id)
    rows = [_row(i, now) for i in items]

    stale = []
    for i in items:
        status = _warranty_status(i, now)
        if status not in ("expired", "expiring"):
            continue
        due = as_utc(i.warranty_expires) if i.warranty_expires else as_utc(now)
        stale.append((0 if status == "expired" else 1, due, i))
    stale.sort(key=lambda t: (t[0], t[1]))
    stale_rows = [_row(i, now) for _rank, _due, i in stale]

    warranty = {"lifetime": 0, "active": 0, "expiring": 0, "expired": 0, "none": 0}
    for r in rows:
        warranty[r["warrantyStatus"]] += 1

    return {
        "generatedAt": iso(now),
        "currency": group.currency,
        "summary": {
            "totalItems": len(rows),
            "staleCount": len(stale_rows),
            "warranty": warranty,
        },
        "items": stale_rows,
    }


REPORTS: list[ReportSpec] = [
    ReportSpec(
        id="inventory",
        title="Inventory valuation & insurance summary",
        build=inventory_payload,
        csv_columns=(
            "Name", "Location", "Labels", "Serial", "Purchased from",
            "Purchase date", "Purchase price", "Quantity", "Line value",
            "Insured", "Warranty",
        ),
    ),
    ReportSpec(
        id="attention",
        title="Attention digest",
        build=digest_payload,
    ),
    ReportSpec(
        id="completeness",
        title="Item data-completeness",
        build=completeness_payload,
    ),
    ReportSpec(
        id="stale",
        title="Expiring & stale items",
        build=stale_payload,
    ),
]
