"""Cross-module regression: report path and alert digest apply ONE date rule.

The inventory report (`app.api.reports._warranty_status`) and the household alert
digest (`app.services.alerts.alert_digest`) both classify a warranty as
active / expiring / expired, and after the `report_dates` refactor both had to
derive the household-local calendar day through the one shared helper. This pins
that contract: a single fixture (one item whose warranty expires on a known date,
in a group whose household runs a fixed timezone) must classify identically
through the report path and the digest path — or the report and the notification
fall over two different days.
"""
from datetime import date, datetime, timezone

from app.extensions import db
from app.models import Item
from app.services import report_dates
from app.services.alerts import alert_digest


FROZEN_NOW = datetime(2026, 3, 1, 13, 0, tzinfo=timezone.utc)
ZONE = "Pacific/Auckland"
# A calendar date, saved the way the UI's date input does: "YYYY-MM-DD" -> 00:00.
# Stored as UTC midnight, so the stored value is never shifted — only compared.
EXPIRING_TODAY = datetime(2026, 3, 2)
EXPIRED_YESTERDAY = datetime(2026, 3, 1)


def _add_warranty_item(app, gid, name, expires):
    with app.app_context():
        db.session.add(Item(name=name, group_id=gid, warranty_expires=expires))
        db.session.commit()
        return db.session.query(Item).filter_by(name=name, group_id=gid).one()


def _report_warranty_status(auth_client, name):
    r = auth_client.get("/api/v1/reports/inventory").get_json()
    return next(i["warrantyStatus"] for i in r["items"] if i["name"] == name)


def _local_today(app, gid, now):
    with app.app_context():
        return report_dates.today_local(gid, now=now)


def test_report_and_digest_apply_the_same_date_rule(app, auth_client, gid, monkeypatch):
    """One fixture expiring today -> both the report and the digest say "expiring";
    the same fixture once the local day has moved on -> both agree it is expired."""
    monkeypatch.setitem(app.config["SETTINGS"].values, "TZ", ZONE)
    monkeypatch.setattr("app.api.reports.utcnow", lambda: FROZEN_NOW)

    with app.app_context():
        db.session.add(Item(name="Kettle", group_id=gid, warranty_expires=EXPIRING_TODAY))
        db.session.commit()

    # 2026-03-01T13:00Z is already Mar 2 in Pacific/Auckland: the household-local
    # day the comparisons run against is Mar 2, not UTC's Mar 1.
    assert _local_today(app, gid, FROZEN_NOW) == date(2026, 3, 2)

    status = _report_warranty_status(auth_client, "Kettle")
    with app.app_context():
        digest = alert_digest(gid, now=FROZEN_NOW)

    # Expiring today is inside both windows (inclusive at the edge) -> the same
    # fixture gets the same classification: report "expiring" == digest lists it.
    assert status == "expiring"
    assert digest["counts"]["warrantyExpiringSoon"] == 1
    assert [w["name"] for w in digest["warrantyExpiringSoon"]] == ["Kettle"]


def test_report_and_digest_agree_the_day_after_the_expiry(app, auth_client, gid, monkeypatch):
    monkeypatch.setitem(app.config["SETTINGS"].values, "TZ", ZONE)
    monkeypatch.setattr("app.api.reports.utcnow", lambda: FROZEN_NOW)

    with app.app_context():
        db.session.add(Item(name="Kettle", group_id=gid, warranty_expires=EXPIRED_YESTERDAY))
        db.session.commit()

    status = _report_warranty_status(auth_client, "Kettle")
    with app.app_context():
        digest = alert_digest(gid, now=FROZEN_NOW)

    # Expiry before the household-local day -> report "expired" and the digest no
    # longer counts it as expiring. The stored value is never shifted.
    assert status == "expired"
    assert digest["counts"]["warrantyExpiringSoon"] == 0
