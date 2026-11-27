"""Registry-level report health audit.

One table-driven pass over every report/digest the report registry knows how to
build. Before a registry-built row reaches a consumer — an inventory response or
a notification body — it must satisfy the ReportRow contract:

* ``status_label`` is non-empty;
* ``status_tone`` is a tone from the contract (``ok`` / ``warn`` / ``bad``);
* a row that links to an item carries a non-empty ``action_url``;
* the row went through the registry's integrity check (``validate_report_row``);
* the row's dates were resolved through the shared time helper, not inline math.

Every violation is reported against the report id, so a half-migrated report is
identifiable from the failure alone.

Wired into the same gate as the digest integrity tests: this module lives in
``backend/tests/`` alongside them and is therefore collected by the same backend
``pytest -q`` CI step that runs the digest integrity tests.
"""
import inspect
from datetime import datetime

import pytest

from app.extensions import db
from app.models import Item, MaintenanceEntry
from app.services import report_registry
from app.services.report_registry import ReportRow, validate_report_row

VALID_STATUS_TONES = ("ok", "warn", "bad")


def _health_problems(report_id, row, *, actionable) -> list:
    """The ReportRow health contract, as violations — each keyed by report id."""
    problems = []
    if not (row.status_label or "").strip():
        problems.append(f"{report_id}: status_label must be non-empty")
    if row.status_tone not in VALID_STATUS_TONES:
        problems.append(
            f"{report_id}: status_tone {row.status_tone!r} is not a ReportRow tone")
    if actionable and not (row.action_url or "").strip():
        problems.append(
            f"{report_id}: actionable row {row.item_ref} carries an empty action_url")
    return problems


def _overdue_checkout_row(app, gid):
    item = Item(name="Ladder", group_id=gid, checked_out=True, checked_out_to="Bob",
                checkout_due=datetime(2026, 8, 1))
    db.session.add(item)
    db.session.flush()
    return report_registry.build_checkout_overdue_row(item, action_url=f"/#/items/{item.id}")


def _warranty_soon_row(app, gid):
    item = Item(name="Laptop", group_id=gid, warranty_expires=datetime(2026, 8, 20))
    db.session.add(item)
    db.session.flush()
    return report_registry.build_warranty_soon_row(item, action_url=f"/#/items/{item.id}")


def _maintenance_overdue_row(app, gid):
    item = Item(name="Drill", group_id=gid)
    db.session.add(item)
    db.session.flush()
    entry = MaintenanceEntry(name="Annual service", item_id=item.id,
                              scheduled_date=datetime(2026, 8, 1))
    db.session.add(entry)
    db.session.flush()
    return report_registry.build_maintenance_overdue_row(entry, action_url="/#/maintenance")


def _item_row(app, gid):
    item = Item(name="Drill", group_id=gid, purchase_price=100, quantity=1)
    db.session.add(item)
    db.session.flush()
    return report_registry.build_item_row(item, action_url=f"/#/items/{item.id}")


REGISTERED_REPORTS = [
    pytest.param("alert-digest:overdue-checkout", _overdue_checkout_row,
                 id="alert-digest_overdue_checkout"),
    pytest.param("alert-digest:warranty-expiring-soon", _warranty_soon_row,
                 id="alert-digest_warranty_expiring_soon"),
    pytest.param("alert-digest:maintenance-overdue", _maintenance_overdue_row,
                 id="alert-digest_maintenance_overdue"),
    pytest.param("inventory-report:item", _item_row, id="inventory-report_item"),
]


@pytest.mark.parametrize(("report_id", "make"), REGISTERED_REPORTS)
def test_every_registered_report_row_is_healthy(app, gid, report_id, make):
    """The registry's own rows must satisfy the ReportRow health contract."""
    with app.app_context():
        row = make(app, gid)
        problems = _health_problems(report_id, row, actionable=True)
        assert problems == [], "\n".join(problems)
        # The registry's integrity check is the gate: the row resolves or the
        # report fails loudly instead of shipping a stale row.
        assert validate_report_row(row, group_id=gid, db=db) is row


def test_report_registry_dates_route_through_the_shared_time_helper():
    """No report surface may inline its own clock: dates come from timeutil."""
    src = inspect.getsource(report_registry)
    assert "from ..timeutil import" in src, (
        "report registry must resolve dates through the shared time helper")
    assert "from datetime import datetime" not in src, (
        "report registry must not build its own datetime clock")


BROKEN_REPORT_ID = "alert-digest:overdue-checkout"


def test_health_audit_flags_a_broken_registry_row(app, gid):
    """The audit must catch a half-migrated registry row — and name the report."""
    with app.app_context():
        row = ReportRow(
            item_ref="item:00000000-0000-0000-0000-000000000000",
            title="Ghost",
            status_label="",
            status_tone="bogus",
            reason="The item was deleted before the row was built.",
            action_url="",
        )
        problems = _health_problems(BROKEN_REPORT_ID, row, actionable=True)
        joined = "\n".join(problems)
        assert BROKEN_REPORT_ID in joined, problems
        assert "status_label" in joined, problems
        assert "status_tone" in joined, problems
        assert "action_url" in joined, problems
        with pytest.raises(ValueError):
            validate_report_row(row, group_id=gid, db=db)
