"""Local time zone: storage stays UTC, rendering and date-only input use TZ."""
import csv
import io
from datetime import datetime, timezone

import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.settings import load_settings


def _make_app(tmp_path, tz):
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


# Overrides conftest's `app`, so auth_client/gid run against a New York app.
@pytest.fixture()
def app(tmp_path):
    app = _make_app(tmp_path, "America/New_York")
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_to_local_converts_utc_instant_to_configured_zone(app):
    from app.timeutil import to_local
    with app.app_context():
        local = to_local(datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc))
    assert (local.year, local.month, local.day, local.hour) == (2025, 12, 31, 22)


def test_to_local_treats_naive_value_as_utc(app):
    from app.timeutil import to_local
    with app.app_context():
        local = to_local(datetime(2026, 1, 1, 3, 0))
    assert (local.day, local.hour) == (31, 22)


def test_csv_date_columns_stay_calendar_dates_under_a_local_zone(app, gid):
    """Item dates are calendar dates stored as UTC midnight: the UI's
    <input type=date> posts "YYYY-MM-DD", items._parse_dt stores 00:00, and the
    UI shows slice(0, 10). Shifting them through to_local would export Jan 1 as
    Dec 31 west of UTC, so CSV keeps them zone-free under any TZ."""
    from app.models import Item
    from app.services.csv_io import export_items, import_items
    with app.app_context():
        assert import_items(gid, "HB.name,HB.purchase_time\nKettle,2026-01-01\n") == 1
        item = db.session.query(Item).filter_by(name="Kettle").one()
        assert item.purchase_date.replace(tzinfo=None) == datetime(2026, 1, 1, 0, 0)
        rows = list(csv.DictReader(io.StringIO(export_items(gid))))
    kettle = next(r for r in rows if r["HB.name"] == "Kettle")
    assert kettle["HB.purchase_time"] == "2026-01-01"


def test_unknown_zone_warns_and_falls_back_to_utc(tmp_path):
    s = load_settings(env={"HBOX_TZ": "Mars/Olympus"}, ha_options={})
    assert any("Mars/Olympus" in w for w in s.warnings)

    from app.timeutil import local_zone
    bad = _make_app(tmp_path, "Mars/Olympus")
    with bad.app_context():
        assert local_zone() == timezone.utc
        db.session.remove()
        db.drop_all()


def test_default_zone_is_utc():
    s = load_settings(env={}, ha_options={})
    assert s.TZ == "UTC"
    assert not any("TZ" in w for w in s.warnings)
