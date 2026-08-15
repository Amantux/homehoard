"""The household alert digest — overdue lends, warranties expiring soon, overdue
maintenance. One definition, consumed by the HA summary sensor and the notifier
dispatch so the two never disagree about what counts as an alert.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import Item, MaintenanceEntry
from . import vault

# Warranties within this window are "expiring soon" for alerting purposes.
WARRANTY_SOON_DAYS = 30


def active_warranty_items(group_id):
    """Items with a future warranty expiry (excludes lifetime + sold)."""
    return (
        vault.never_hidden(db.session.query(Item))
        .filter(
            Item.group_id == group_id,
            Item.sold_date.is_(None),
            Item.lifetime_warranty.is_(False),
            Item.warranty_expires.isnot(None),
        )
        .all()
    )


def open_maintenance(group_id):
    """Scheduled, not-yet-completed maintenance entries for the group's items."""
    return (
        vault.never_hidden(db.session.query(MaintenanceEntry)
                           .join(Item, Item.id == MaintenanceEntry.item_id))
        .options(joinedload(MaintenanceEntry.item))  # digest reads m.item.name
        .filter(
            Item.group_id == group_id,
            MaintenanceEntry.completed_date.is_(None),
            MaintenanceEntry.scheduled_date.isnot(None),
        )
        .all()
    )


def alert_digest(group_id, now=None):
    """Structured digest plus a plain-text summary for a notification body.

    `now` is injectable for testing. `isEmpty` is True when nothing needs
    attention, so a caller can skip sending a "nothing to report" message."""
    now = now or datetime.utcnow()
    items = db.session.query(Item).filter_by(group_id=group_id).all()

    overdue_checkouts = [
        i for i in items
        if i.checked_out and i.checkout_due and i.checkout_due < now
    ]
    warranty_soon = [
        i for i in active_warranty_items(group_id)
        if now <= i.warranty_expires <= now + timedelta(days=WARRANTY_SOON_DAYS)
    ]
    maintenance_overdue = [
        m for m in open_maintenance(group_id) if m.scheduled_date < now
    ]
    # include_hidden=False, NOT the default: the dispatcher runs inside a
    # request, and if that session happened to be vault-unlocked the default
    # visibility would put a hidden consumable's NAME on someone's phone. A
    # notification outlives the session; never-hidden, like everything above.
    from .restock import restock_suggestions
    low = restock_suggestions(group_id, include_hidden=False)

    # Tap-through links make the digest actionable — but only when the operator
    # told us the browser-facing URL (PUBLIC_URL): under ingress the server
    # cannot derive it, and a wrong guess is a broken link on a phone.
    from flask import current_app, has_app_context
    base = ""
    if has_app_context():
        base = (current_app.config.get("PUBLIC_URL") or "").rstrip("/")

    def _link(path):
        return f" {base}/#{path}" if base else ""

    lines = []
    if overdue_checkouts:
        names = ", ".join(
            f"{i.name}" + (f" (to {i.checked_out_to})" if i.checked_out_to else "")
            for i in overdue_checkouts[:10])
        lines.append(f"Overdue for return ({len(overdue_checkouts)}): {names}."
                     + _link("/checkouts"))
    if low:
        names = ", ".join(f"{r['name']} (buy {r['suggestedQuantity']:g})"
                          for r in low[:10])
        lines.append(f"Running low ({len(low)}): {names}." + _link("/restock"))
    if warranty_soon:
        names = ", ".join(
            f"{i.name} — {i.warranty_expires.date().isoformat()}"
            for i in sorted(warranty_soon, key=lambda x: x.warranty_expires)[:10])
        lines.append(
            f"Warranty expiring within {WARRANTY_SOON_DAYS} days "
            f"({len(warranty_soon)}): {names}")
    if maintenance_overdue:
        names = ", ".join(
            f"{m.name}" + (f" [{m.item.name}]" if m.item else "")
            for m in sorted(maintenance_overdue, key=lambda x: x.scheduled_date)[:10])
        lines.append(f"Maintenance overdue ({len(maintenance_overdue)}): {names}."
                     + _link("/maintenance"))

    counts = {
        "restock": len(low),
        "overdueCheckouts": len(overdue_checkouts),
        "warrantyExpiringSoon": len(warranty_soon),
        "maintenanceOverdue": len(maintenance_overdue),
    }
    return {
        "counts": counts,
        "overdueCheckouts": [{"id": i.id, "name": i.name,
                              "to": i.checked_out_to} for i in overdue_checkouts],
        "warrantyExpiringSoon": [
            {"id": i.id, "name": i.name,
             "expires": i.warranty_expires.date().isoformat()}
            for i in sorted(warranty_soon, key=lambda x: x.warranty_expires)],
        "maintenanceOverdue": [
            {"id": m.id, "name": m.name, "itemId": m.item_id,
             "scheduled": m.scheduled_date.date().isoformat()}
            for m in sorted(maintenance_overdue, key=lambda x: x.scheduled_date)],
        "isEmpty": not any(counts.values()),
        "text": "\n".join(lines) if lines else "No HomeHoard alerts.",
    }
