"""The report registry: ReportRow contract, validation, serialization."""
import dataclasses
from datetime import datetime

import pytest

from app.extensions import db
from app.models import Item, MaintenanceEntry
from app.services.report_registry import ReportRow
from app.services.report_registry import build_checkout_overdue_row
from app.services.report_registry import build_maintenance_overdue_row
from app.services.report_registry import build_warranty_soon_row
from app.services.report_registry import serialize_checkout_overdue_row
from app.services.report_registry import serialize_maintenance_overdue_row
from app.services.report_registry import serialize_report_row
from app.services.report_registry import serialize_warranty_soon_row
from app.services.report_registry import validate_report_row


ROW_FIELDS = [
    "item_ref",
    "title",
    "status_label",
    "status_tone",
    "reason",
    "action_url",
]


def _resolver(ref):
    """Stand-in resolver: 'item:<id>' / 'maintenance:<id>' -> live row or None."""
    kind, _, rid = ref.partition(":")
    if kind == "item" and rid:
        return db.session.get(Item, rid)
    if kind == "maintenance" and rid:
        return db.session.get(MaintenanceEntry, rid)
    return None


def _item(gid, name):
    it = Item(name=name, group_id=gid)
    db.session.add(it)
    db.session.flush()
    return it


def test_valid_row_passes(app, gid):
    with app.app_context():
        it = _item(gid, "Drill")
        row = ReportRow(
            item_ref=f"item:{it.id}",
            title="Drill",
            status_label="Overdue for return",
            status_tone="bad",
            reason="Was due back before today.",
            action_url=f"/#/items/{it.id}",
        )
        assert validate_report_row(row, resolver=_resolver) is row


def test_unknown_item_ref_raises(app):
    with app.app_context():
        row = ReportRow(
            item_ref="item:123e4567-e89b-12d3-a456-426614174000",
            title="Ghost",
            status_label="",
            status_tone="bad",
            reason="The item was deleted before the row was built.",
            action_url="",
        )
        with pytest.raises(ValueError):
            validate_report_row(row, resolver=_resolver)


def test_deleted_item_ref_is_rejected(app, gid):
    """A row pointing at a deleted item is a bug, not a row to render: the gate
    refuses the ref instead of letting a stale row through."""
    with app.app_context():
        it = _item(gid, "Drill")
        row = ReportRow(
            item_ref=f"item:{it.id}",
            title="Drill",
            status_label="Overdue",
            status_tone="bad",
            reason="Overdue for return.",
            action_url=f"/#/items/{it.id}",
        )
        db.session.delete(it)
        db.session.flush()
        with pytest.raises(ValueError):
            validate_report_row(row, group_id=gid, db=db)


def test_maintenance_item_ref_validates(app, gid):
    with app.app_context():
        it = _item(gid, "Drill")
        m = MaintenanceEntry(name="Annual service", item_id=it.id)
        db.session.add(m)
        db.session.flush()
        row = ReportRow(
            item_ref=f"maintenance:{m.id}",
            title="Annual service",
            status_label="Overdue",
            status_tone="warn",
            reason="Scheduled before today.",
            action_url="",
        )
        assert validate_report_row(row, resolver=_resolver) is row


def test_report_row_has_exactly_the_six_contract_fields():
    assert [f.name for f in dataclasses.fields(ReportRow)] == ROW_FIELDS


def test_serialize_round_trips():
    row = ReportRow(
        item_ref="item:abc",
        title="Drill",
        status_label="Overdue",
        status_tone="bad",
        reason="Overdue for return.",
        action_url="/#/items/abc",
    )
    data = serialize_report_row(row)
    assert list(data) == ROW_FIELDS
    assert ReportRow(**data) == row


def test_group_scoped_validation(app, gid):
    with app.app_context():
        it = _item(gid, "Drill")
        row = ReportRow(
            item_ref=f"item:{it.id}",
            title="Drill",
            status_label="Overdue",
            status_tone="bad",
            reason="Overdue for return.",
            action_url=f"/#/items/{it.id}",
        )
        assert validate_report_row(row, group_id=gid, db=db) is row


def test_checkout_overdue_row_is_item_scoped_and_valid(app, gid):
    with app.app_context():
        it = _item(gid, "Ladder")
        it.checked_out = True
        it.checked_out_to = "Bob"
        it.checkout_due = datetime(2026, 8, 1)
        db.session.flush()
        row = build_checkout_overdue_row(it, action_url=f"/#/items/{it.id}")
        assert row.item_ref == f"item:{it.id}"
        assert row.title == "Ladder"
        assert row.status_label == "Overdue for return"
        assert row.status_tone == "bad"
        assert row.reason == "Was due back before 2026-08-01. (to Bob)"
        assert row.action_url == f"/#/items/{it.id}"
        assert validate_report_row(row, resolver=_resolver) is row
        assert serialize_checkout_overdue_row(row, it) == {
            "id": it.id, "name": "Ladder", "to": "Bob"}


def test_warranty_soon_row_uses_registry_status_and_serializes(app, gid):
    with app.app_context():
        it = _item(gid, "Laptop")
        it.warranty_expires = datetime(2026, 8, 20)
        db.session.flush()
        row = build_warranty_soon_row(it, action_url=f"/#/items/{it.id}")
        assert row.item_ref == f"item:{it.id}"
        assert row.status_label == "Expiring soon"
        assert row.status_tone == "warn"
        assert row.reason == "Warranty expires 2026-08-20."
        assert validate_report_row(row, resolver=_resolver) is row
        assert serialize_warranty_soon_row(row, it) == {
            "id": it.id, "name": "Laptop", "expires": "2026-08-20"}


def test_maintenance_overdue_row_is_maintenance_scoped_and_valid(app, gid):
    with app.app_context():
        it = _item(gid, "Drill")
        m = MaintenanceEntry(name="Annual service", item_id=it.id,
                              scheduled_date=datetime(2026, 8, 1))
        db.session.add(m)
        db.session.flush()
        row = build_maintenance_overdue_row(m, action_url="/#/maintenance")
        assert row.item_ref == f"maintenance:{m.id}"
        assert row.title == "Annual service"
        assert row.status_label == "Overdue"
        assert row.status_tone == "warn"
        assert row.reason == "Scheduled before 2026-08-01."
        assert validate_report_row(row, resolver=_resolver) is row
        assert serialize_maintenance_overdue_row(row, m) == {
            "id": m.id, "name": "Annual service", "itemId": it.id,
            "scheduled": "2026-08-01"}
