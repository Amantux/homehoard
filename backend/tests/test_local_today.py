"""'Today' for overdue/expiring checks is the household's calendar day (TZ).

Item dates are calendar dates stored as UTC midnight (see test_timezone.py), so
an alert compares the stored `.date()` against the local date of `now` — never
the stored value shifted through a zone, and never `now` in UTC.

The frozen instant 2026-03-01T13:00Z is already Mar 2 in Auckland (UTC+13 in
March) but still Mar 1 in UTC, so every case flips between the two zones.
"""
from datetime import datetime, timezone

import pytest

from app import create_app
from app.config import Config
from app.extensions import db

NOW = datetime(2026, 3, 1, 13, 0, tzinfo=timezone.utc)


def _make_app(tmp_path, tz):
    # Same shape as test_timezone.py's factory (tests/ is not a package).
    class TZConfig(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = f"sqlite:///{tmp_path}/test.db"
        DISABLE_AUTH = False
        SECRET_KEY = "test-secret-key-that-is-long-enough-32b"
        RATELIMIT_ENABLED = False
        PROXY_HOPS = 0
        WORKER_ENABLED = False
        TZ = tz

    return create_app(TZConfig)


@pytest.fixture(params=["Pacific/Auckland", "UTC"])
def app(request, tmp_path):
    app = _make_app(tmp_path, request.param)
    app.tz_name = request.param
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def seeded(app, gid):
    """Warranty expiring 2026-03-02 and maintenance scheduled 2026-03-01,
    both stored at UTC midnight the way the UI's date input saves them."""
    from app.models import Item, MaintenanceEntry
    with app.app_context():
        kettle = Item(name="Kettle", group_id=gid,
                      warranty_expires=datetime(2026, 3, 2))
        furnace = Item(name="Furnace", group_id=gid)
        db.session.add_all([kettle, furnace])
        db.session.flush()
        db.session.add(MaintenanceEntry(item_id=furnace.id, name="Filter change",
                                        scheduled_date=datetime(2026, 3, 1)))
        db.session.commit()
    return app.tz_name == "Pacific/Auckland"


def test_alert_digest_uses_local_calendar_day(app, gid, seeded):
    from app.services.alerts import alert_digest
    auckland = seeded
    with app.app_context():
        d = alert_digest(gid, now=NOW)
    names = [w["name"] for w in d["warrantyExpiringSoon"]]
    if auckland:
        # Local today is Mar 2: the warranty expires today (still within the
        # window) and the Mar 1 maintenance is a day overdue.
        assert names == ["Kettle"]
        assert d["counts"]["maintenanceOverdue"] == 1
    else:
        # UTC today is Mar 1: the maintenance is due today, not overdue.
        assert names == ["Kettle"]
        assert d["counts"]["maintenanceOverdue"] == 0


def test_alert_digest_expired_yesterday_drops_out_locally(app, gid, seeded):
    """A warranty that expired on the local yesterday is no longer 'soon'."""
    from app.models import Item
    from app.services.alerts import alert_digest
    auckland = seeded
    with app.app_context():
        item = db.session.query(Item).filter_by(name="Kettle").one()
        item.warranty_expires = datetime(2026, 3, 1)
        db.session.commit()
        d = alert_digest(gid, now=NOW)
    assert d["counts"]["warrantyExpiringSoon"] == (0 if auckland else 1)


def test_ha_summary_uses_local_calendar_day(app, auth_client, seeded, monkeypatch):
    import app.api.ha as ha
    monkeypatch.setattr(ha, "utcnow", lambda: NOW)
    auckland = seeded
    s = auth_client.get("/api/v1/ha/summary").get_json()
    assert s["warrantiesExpiring"]["days30"] == 1
    entry = s["maintenance"]["entries"][0]
    if auckland:
        assert s["maintenance"]["overdue"] == 1
        assert s["maintenance"]["upcoming30"] == 0
        assert entry["overdue"] is True
    else:
        assert s["maintenance"]["overdue"] == 0
        assert s["maintenance"]["upcoming30"] == 1
        assert entry["overdue"] is False
    # Serialisation is untouched: the stored calendar date, never shifted.
    assert entry["scheduled"] == "2026-03-01"
    assert s["warrantiesExpiring"]["items"][0]["expires"] == "2026-03-02"


def test_ha_summary_expired_yesterday_drops_out_locally(app, auth_client, seeded,
                                                        monkeypatch):
    from app.models import Item
    import app.api.ha as ha
    monkeypatch.setattr(ha, "utcnow", lambda: NOW)
    auckland = seeded
    with app.app_context():
        item = db.session.query(Item).filter_by(name="Kettle").one()
        item.warranty_expires = datetime(2026, 3, 1)
        db.session.commit()
    s = auth_client.get("/api/v1/ha/summary").get_json()
    assert s["warrantiesExpiring"]["days30"] == (0 if auckland else 1)
