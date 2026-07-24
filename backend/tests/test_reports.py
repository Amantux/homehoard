"""Home-inventory valuation/insurance report."""
from datetime import timedelta

from app.extensions import db
from app.models import Group, Item, Location, User, utcnow


def _gid(app):
    with app.app_context():
        return db.session.query(User).filter_by(email="t@t.com").first().group_id


def test_inventory_report_totals_and_breakdown(app, auth_client):
    gid = _gid(app)
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


def test_inventory_report_csv(app, auth_client):
    gid = _gid(app)
    with app.app_context():
        db.session.add(Item(name="Drill", purchase_price=100, quantity=1, group_id=gid))
        db.session.commit()

    r = auth_client.get("/api/v1/reports/inventory.csv")

    assert r.status_code == 200 and "text/csv" in r.content_type
    body = r.get_data(as_text=True)
    assert "Drill" in body and "Line value" in body


def test_report_requires_auth(client):
    assert client.get("/api/v1/reports/inventory").status_code == 401


def test_report_is_group_scoped(app, auth_client):
    gid = _gid(app)
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
