"""Unit tests for the household-local today / expiring-window helpers."""
from datetime import date, datetime, timedelta, timezone

from app.services import report_dates


FROZEN_NOW = datetime(2026, 3, 1, 13, 0, tzinfo=timezone.utc)


def test_today_local_uses_the_household_zone(app, gid, monkeypatch):
    monkeypatch.setitem(app.config["SETTINGS"].values, "TZ", "Pacific/Auckland")
    monkeypatch.setattr(report_dates, "utcnow", lambda: FROZEN_NOW)
    with app.app_context():
        # 2026-03-01T13:00Z is already Mar 2 in Auckland (UTC+13), still Mar 1 in UTC.
        assert report_dates.today_local(gid) == date(2026, 3, 2)


def test_is_expiring_boundary_is_inclusive_at_today_and_window_edge():
    today = date(2026, 3, 2)
    window_days = 30
    # Within the window: inclusive at `today` and at today + window_days, exclusive beyond.
    assert report_dates.is_expiring(today, window_days, today) is True
    assert report_dates.is_expiring(
        today + timedelta(days=window_days), window_days, today) is True
    assert report_dates.is_expiring(
        today + timedelta(days=window_days + 1), window_days, today) is False
    assert report_dates.is_expiring(
        today - timedelta(days=1), window_days, today) is False
    # A datetime is accepted and compared by calendar day.
    assert report_dates.is_expiring(
        datetime(2026, 3, 2, 5, 0), window_days,
        datetime(2026, 3, 2, tzinfo=timezone.utc)) is True
