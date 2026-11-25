"""Home-inventory valuation/insurance report."""
from datetime import datetime, timedelta, timezone

from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Group, Item, Location, utcnow


# The report reads `utcnow()` for its warranty / urgency thresholds; freeze it so
# the attention-list boundaries below are deterministic, not wall-clock dependent.
NOW = datetime(2026, 3, 1, 13, 0, tzinfo=timezone.utc)


@pytest.fixture()
def frozen_now(monkeypatch):
    import app.api.reports as reports_module
    monkeypatch.setattr(reports_module, "utcnow", lambda: NOW)
    return NOW


def _attention(auth_client):
    return auth_client.get("/api/v1/reports/inventory").get_json()["summary"]["attention"]


def test_inventory_report_totals_and_breakdown(app, auth_client, gid):

    with app.app_context():
        loc = Location(name="Garage", group_id=gid)
        db.session.add(loc)
        db.session.flush()
        db.session.add(Item(name="Drill", purchase_price=100, quantity=1, insured=True,
                            location_id=loc.id, group_id=gid,
                            warranty_expires=utcnow() + timedelta(days=400)))
        db.session.add(Item(name="Ladder", purchase_price=50, quantity=2, insured=False,
                            group_id=gid, warranty_expires=utcnow() - timedelta(days=10)))
        db.session.commit()

    r = auth_client.get("/api/v1/reports/inventory").get_json()

    s = r["summary"]
    assert s["totalItems"] == 2
    assert s["totalValue"] == 200.0        # 100*1 + 50*2
    assert s["insuredValue"] == 100.0
    assert s["uninsuredValue"] == 100.0
    assert s["warranty"]["active"] == 1    # drill: 400d out
    assert s["warranty"]["expired"] == 1   # ladder: past
    assert any(b["name"] == "Garage" and b["value"] == 100.0 for b in r["byLocation"])


def test_inventory_report_attention_expired_warranty(app, auth_client, gid, frozen_now):

    with app.app_context():
        db.session.add(Item(name="Drill", purchase_price=100, quantity=1, insured=True,
                            group_id=gid, purchase_date=datetime(2025, 1, 1),
                            warranty_expires=datetime(2026, 2, 19, 13, 0)))
        db.session.commit()

    attention = _attention(auth_client)

    assert len(attention) == 1
    row = attention[0]
    assert row["name"] == "Drill"
    assert row["severity"] == "expired"
    assert row["reasons"] == ["warranty_expired"]
    assert row["gap"] == "warranty expired on 2026-02-19"
    assert row["due"] == "2026-02-19T13:00:00+00:00"


def test_inventory_report_attention_expiring_warranty(app, auth_client, gid, frozen_now):

    with app.app_context():
        db.session.add(Item(name="Drill", group_id=gid, purchase_price=25,
                            purchase_date=datetime(2025, 1, 1),
                            warranty_expires=datetime(2026, 3, 31, 13, 0)))
        db.session.commit()

    row = _attention(auth_client)[0]
    assert row["severity"] == "expiring"
    assert row["reasons"] == ["warranty_expiring"]
    assert row["gap"] == "warranty expires on 2026-03-31"
    assert row["due"] == "2026-03-31T13:00:00+00:00"


def test_inventory_report_attention_overdue_checkout(app, auth_client, gid, frozen_now):

    with app.app_context():
        db.session.add(Item(name="Drill", group_id=gid, purchase_price=40,
                            purchase_date=datetime(2025, 1, 1), lifetime_warranty=True,
                            checked_out=True, checked_out_to="Sam",
                            checkout_due=datetime(2026, 2, 27, 13, 0)))
        db.session.commit()

    row = _attention(auth_client)[0]
    assert row["severity"] == "stale"
    assert row["reasons"] == ["checkout_overdue"]
    assert row["gap"] == "still out (to Sam) past due 2026-02-27"
    assert row["due"] == "2026-02-27T13:00:00+00:00"


def test_inventory_report_attention_incomplete_key_facts(app, auth_client, gid, frozen_now):

    with app.app_context():
        db.session.add(Item(name="Saw", group_id=gid, purchase_price=Decimal("0.00")))
        db.session.commit()

    row = _attention(auth_client)[0]
    assert row["severity"] == "incomplete"
    assert row["reasons"] == ["incomplete_key_facts"]
    assert row["gap"] == "missing no purchase price, no purchase date, no warranty"
    assert row["due"] is None


def test_inventory_report_attention_merges_reasons_into_one_row(app, auth_client, gid, frozen_now):

    with app.app_context():
        db.session.add(Item(name="Drill", purchase_price=100, quantity=1, group_id=gid,
                            purchase_date=datetime(2025, 1, 1),
                            warranty_expires=datetime(2026, 2, 19, 13, 0),
                            checked_out=True, checked_out_to="Sam",
                            checkout_due=datetime(2026, 2, 27, 13, 0)))
        db.session.commit()

    attention = _attention(auth_client)
    assert len(attention) == 1  # deduped: merged reasons collapse to a single row
    row = attention[0]
    assert row["name"] == "Drill"
    assert row["severity"] == "expired"  # the worst reason leads the row
    assert row["reasons"] == ["warranty_expired", "checkout_overdue"]
    assert row["gap"] == "warranty expired on 2026-02-19"
    assert row["due"] == "2026-02-19T13:00:00+00:00"


def test_inventory_report_attention_sorted_by_severity_then_due(app, auth_client, gid, frozen_now):

    with app.app_context():
        db.session.add_all([
            Item(name="Old Drill", purchase_price=100, quantity=1, group_id=gid,
                 purchase_date=datetime(2025, 1, 1), insured=True,
                 warranty_expires=datetime(2026, 2, 19, 13, 0)),
            Item(name="Soon Drill", group_id=gid, purchase_price=25,
                 purchase_date=datetime(2025, 1, 1), warranty_expires=datetime(2026, 3, 11, 13, 0)),
            Item(name="Later Drill", group_id=gid, purchase_price=25,
                 purchase_date=datetime(2025, 1, 1), warranty_expires=datetime(2026, 3, 31, 13, 0)),
            Item(name="Overdue Saw", group_id=gid, purchase_price=40,
                 purchase_date=datetime(2025, 1, 1), lifetime_warranty=True,
                 checked_out=True, checked_out_to="Sam",
                 checkout_due=datetime(2026, 2, 27, 13, 0)),
            Item(name="Bare Saw", group_id=gid, purchase_price=Decimal("0.00")),
            Item(name="Healthy Drill", group_id=gid, purchase_price=10, quantity=1,
                 purchase_date=datetime(2025, 1, 1), lifetime_warranty=True),
        ])
        db.session.commit()

    attention = _attention(auth_client)

    # Urgency first, due date ascending within a level; the healthy item is absent.
    assert [r["name"] for r in attention] == [
        "Old Drill", "Soon Drill", "Later Drill", "Overdue Saw", "Bare Saw",
    ]
    assert [r["severity"] for r in attention] == [
        "expired", "expiring", "expiring", "stale", "incomplete",
    ]
    # Within the expiring level the soonest warranty comes first.
    assert [r["due"] for r in attention[1:3]] == [
        "2026-03-11T13:00:00+00:00", "2026-03-31T13:00:00+00:00",
    ]


def test_inventory_report_attention_empty_state(app, auth_client, gid, frozen_now):

    with app.app_context():
        db.session.add(Item(name="Healthy Drill", group_id=gid, purchase_price=10, quantity=1,
                            purchase_date=datetime(2025, 1, 1), lifetime_warranty=True))
        db.session.commit()

    assert _attention(auth_client) == []


def test_inventory_report_csv(app, auth_client, gid):

    with app.app_context():
        db.session.add(Item(name="Drill", purchase_price=100, group_id=gid))
        db.session.commit()

    r = auth_client.get("/api/v1/reports/inventory.csv")

    assert r.status_code == 200 and "text/csv" in r.content_type
    body = r.get_data(as_text=True)
    assert "Drill" in body and "Line value" in body


def test_report_requires_auth(client):
    assert client.get("/api/v1/reports/inventory").status_code == 401


def test_report_is_group_scoped(app, auth_client, gid):

    with app.app_context():
        other = Group(name="Other", currency="usd")
        db.session.add(other)
        db.session.flush()
        db.session.add(Item(name="Secret", purchase_price=999, group_id=other.id))
        db.session.add(Item(name="Mine", purchase_price=10, group_id=gid))
        db.session.commit()

    r = auth_client.get("/api/v1/reports/inventory").get_json()

    names = [it["name"] for it in r["items"]]
    assert "Mine" in names and "Secret" not in names
    assert r["summary"]["totalValue"] == 10.0  # other group's 999 excluded
