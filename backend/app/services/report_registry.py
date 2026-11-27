"""The report registry — the one home of the ReportRow contract.

Every report and digest surface (the alerts digest, the inventory report, and
whatever comes next) renders the same typed row instead of hand-rolling its own
shape:

* ``ReportRow`` — the single row contract: what the row is about, how it reads,
  why it matters, and where the operator can act.
* ``validate_report_row`` — the integrity gate: a row must resolve to a real item
  before it is rendered or sent.
* ``serialize_report_row`` — the JSON-ready dict both sides agree on.

A row's ``item_ref`` names what it is about, prefixed by kind: ``item:<id>`` for
an inventory item, ``maintenance:<id>`` for a maintenance entry.
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from ..models import Item, MaintenanceEntry
from ..timeutil import as_utc, utcnow

# Warranties within this window of the expiry date are "expiring" for report
# purposes. (The alert digest applies its own shorter window — services/alerts.)
_EXPIRING_SOON_DAYS = 60

_STATUS_LABELS = {
    "lifetime": "Lifetime",
    "active": "Active",
    "expiring": "Expiring soon",
    "expired": "Expired",
    "none": "—",
}

# Plain-language tone for a warranty status: 'ok' healthy, 'warn' watch,
# 'bad' past due. Derived here so every report surface renders one tone.
_STATUS_TONES = {
    "lifetime": "ok",
    "active": "ok",
    "expiring": "warn",
    "expired": "bad",
    "none": "ok",
}


@dataclass
class ReportRow:
    """One actionable report/digest entry.

    ``status_tone`` is the plain-language tone ('ok' / 'warn' / 'bad'); consumers
    render from the field rather than re-deriving presentation per surface.
    """

    item_ref: str
    title: str
    status_label: str
    status_tone: str
    reason: str
    action_url: str = ""


def serialize_report_row(row: ReportRow) -> dict:
    """The JSON-ready dict for a row — the wire shape of the registry contract."""
    return {
        "item_ref": row.item_ref,
        "title": row.title,
        "status_label": row.status_label,
        "status_tone": row.status_tone,
        "reason": row.reason,
        "action_url": row.action_url,
    }


def validate_report_row(
    row: ReportRow,
    resolver: Callable[[str], Any] = None,
    *,
    group_id: str | None = None,
    db: Any = None,
) -> ReportRow:
    """Validate that a report row's item_ref resolves to a real item.

    ``resolver`` lets a caller that already holds the queried rows supply its own
    lookup; without one the row is checked within the household via ``group_id``
    + ``db`` (the same standard session lookups every service uses).

    Raises ``ValueError`` when the item_ref does not resolve — a report that
    points at a deleted or unknown item is a bug, not a row to render.
    """
    ref = row.item_ref
    if resolver is not None:
        resolved = resolver(ref)
    else:
        resolved = _lookup(ref, group_id=group_id, db=db)
    if resolved is None:
        raise ValueError(
            f"report row item_ref does not resolve to a real item: {ref!r}"
        )
    return row


def _lookup(item_ref: str, *, group_id: str | None = None, db: Any = None):
    """Resolve an item_ref ('item:<id>' / 'maintenance:<id>') within a group."""
    kind, _, rid = item_ref.partition(":")
    if kind == "item" and rid:
        q = db.session.query(Item).filter(Item.id == rid)
        if group_id is not None:
            q = q.filter(Item.group_id == group_id)
        return q.first()
    if kind == "maintenance" and rid:
        entry = db.session.get(MaintenanceEntry, rid)
        if entry is None:
            return None
        if group_id is not None and (
            entry.item is None or entry.item.group_id != group_id
        ):
            return None
        return entry
    return None


def warranty_status(item: Item, now) -> str:
    """One of: lifetime, active, expiring, expired, none — the row's status source."""
    if item.lifetime_warranty:
        return "lifetime"
    if not item.warranty_expires:
        return "none"
    if as_utc(item.warranty_expires) < now:
        return "expired"
    if as_utc(item.warranty_expires) < now + timedelta(days=_EXPIRING_SOON_DAYS):
        return "expiring"
    return "active"


def build_item_row(item: Item, *, now=None, action_url: str = "") -> ReportRow:
    """Build the actionable report row for one inventory item.

    The registry is the only producer of rows: a surface hands over the item and
    gets a ReportRow back instead of hand-rolling its own row dict. The item_ref
    names the item the row is about (`item:<id>`), which is what the registry's
    validator resolves later.
    """
    now = as_utc(now) or utcnow()
    status = warranty_status(item, now)
    return ReportRow(
        item_ref=f"item:{item.id}",
        title=item.name,
        status_label=_STATUS_LABELS.get(status, status),
        status_tone=_STATUS_TONES.get(status, "ok"),
        reason=_status_reason(item, status),
        action_url=action_url,
    )


def serialize_item_row(row: ReportRow, item: Item, *, now) -> dict:
    """Map a registry-built ReportRow back onto the inventory row keys.

    The inventory report's item-row shape (valuation + warranty fields) is owned
    here as well, so reports.py only calls into the registry and never builds the
    row dict itself. The ReportRow fields themselves ride along on the row, so
    report consumers render from the row contract rather than re-deriving a label
    or a link per surface.
    """
    from ..schemas.serializers import iso, num  # local: schemas imports services

    from ..services import money

    out = {
        "id": item.id,
        "name": row.title,
        "location": item.location.name if item.location else "",
        "labels": [lbl.name for lbl in item.labels],
        "serialNumber": item.serial_number or "",
        "purchaseFrom": item.purchase_from or "",
        "purchaseDate": iso(item.purchase_date),
        "purchasePrice": money.out(item.purchase_price) or 0,
        "quantity": num(item.quantity) or 1,
        "lineValue": money.out(money.line_total(item.purchase_price, item.quantity)),
        "insured": bool(item.insured),
        "warrantyStatus": warranty_status(item, now),
        "imageId": next((a.document_id for a in item.attachments if a.primary), None),
    }
    # The ReportRow fields ride along on the inventory row as well: the SPA
    # renders report rows from these fields instead of re-deriving a label or a
    # link per surface. The valuation keys above stay for the CSV / insurance doc.
    out.update(serialize_report_row(row))
    return out


def build_checkout_overdue_row(item: Item, *, action_url: str = "") -> ReportRow:
    """Overdue lend: the item went out and its due date has passed.

    The report registry is the only producer of rows, so the digest's
    ``overdueCheckouts`` kind gets its row here rather than in the alert service.
    The operator acts from the item's own page, which carries the check-out flow.
    """
    due = item.checkout_due.date().isoformat() if item.checkout_due else ""
    reason = f"Was due back before {due}."
    if item.checked_out_to:
        reason = f"{reason} (to {item.checked_out_to})"
    return ReportRow(
        item_ref=f"item:{item.id}",
        title=item.name,
        status_label="Overdue for return",
        status_tone="bad",
        reason=reason,
        action_url=action_url,
    )


def build_warranty_soon_row(item: Item, *, action_url: str = "") -> ReportRow:
    """Warranty expiring within the alert window — still covered, lapsing soon."""
    expires = item.warranty_expires.date().isoformat() if item.warranty_expires else ""
    return ReportRow(
        item_ref=f"item:{item.id}",
        title=item.name,
        status_label=_STATUS_LABELS["expiring"],
        status_tone=_STATUS_TONES["expiring"],
        reason=f"Warranty expires {expires}.",
        action_url=action_url,
    )


def build_maintenance_overdue_row(entry: MaintenanceEntry, *, action_url: str = "") -> ReportRow:
    """Overdue maintenance: scheduled before today, not yet completed."""
    scheduled = entry.scheduled_date.date().isoformat() if entry.scheduled_date else ""
    return ReportRow(
        item_ref=f"maintenance:{entry.id}",
        title=entry.name,
        status_label="Overdue",
        status_tone="warn",
        reason=f"Scheduled before {scheduled}.",
        action_url=action_url,
    )


def serialize_checkout_overdue_row(row: ReportRow, item: Item) -> dict:
    """Map an overdue-checkout row back onto the digest's per-entry keys."""
    return {"id": item.id, "name": row.title, "to": item.checked_out_to}


def serialize_warranty_soon_row(row: ReportRow, item: Item) -> dict:
    """Map a warranty-soon row back onto the digest's per-entry keys."""
    return {
        "id": item.id,
        "name": row.title,
        "expires": item.warranty_expires.date().isoformat() if item.warranty_expires else "",
    }


def serialize_maintenance_overdue_row(row: ReportRow, entry: MaintenanceEntry) -> dict:
    """Map an overdue-maintenance row back onto the digest's per-entry keys."""
    return {
        "id": entry.id,
        "name": row.title,
        "itemId": entry.item_id,
        "scheduled": entry.scheduled_date.date().isoformat() if entry.scheduled_date else "",
    }


def _status_reason(item: Item, status: str) -> str:
    """A short, plain-language why-this-row-exists reason."""
    if status == "lifetime":
        return "Covered by the lifetime warranty."
    if status == "none":
        return "No warranty on file."
    expires = as_utc(item.warranty_expires).date().isoformat() if item.warranty_expires else ""
    if status == "expired":
        return f"Warranty expired {expires}."
    if status == "expiring":
        return f"Warranty expires {expires}."
    return f"Covered until {expires}."
