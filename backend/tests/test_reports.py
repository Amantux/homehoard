"""Home-inventory valuation/insurance report."""
import csv
from datetime import timedelta

from app.extensions import db
from app.models import Group, Item, Location, utcnow


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


def test_inventory_report_csv(app, auth_client, gid):

    with app.app_context():
        db.session.add(Item(name="Drill", purchase_price=100, quantity=1, group_id=gid))
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


def test_reports_index_lists_registered_reports(auth_client):
    from app.api.reports_registry import REPORTS

    r = auth_client.get("/api/v1/reports")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)
    # The index mirrors the registry exactly: id + title per registered report.
    assert data == [{"id": s.id, "title": s.title} for s in REPORTS]


def test_reports_index_requires_auth(client):
    assert client.get("/api/v1/reports").status_code == 401


def test_report_unknown_id_returns_404(auth_client):
    assert auth_client.get("/api/v1/reports/nope").status_code == 404


def test_attention_digest_report_reuses_alert_logic(auth_client, app, gid):
    with app.app_context():
        db.session.add(Item(name="AA batteries", quantity=1, min_quantity=4,
                            target_quantity=12, group_id=gid))
        db.session.add(Item(name="Drill", purchase_price=100, quantity=1, group_id=gid,
                            warranty_expires=utcnow() + timedelta(days=10)))
        db.session.commit()

    r = auth_client.get("/api/v1/reports/attention").get_json()

    assert r["isEmpty"] is False
    assert r["currency"] == "usd"
    assert r["counts"]["restock"] == 1
    assert r["counts"]["warrantyExpiringSoon"] == 1
    assert {e["name"] for e in r["warrantyExpiringSoon"]} == {"Drill"}


def test_completeness_report_flags_missing_facts(auth_client, app, gid):
    with app.app_context():
        db.session.add(Item(name="Drill", group_id=gid, quantity=1))
        db.session.commit()

    r = auth_client.get("/api/v1/reports/completeness").get_json()

    assert r["summary"]["totalItems"] == 1
    # A bare item is missing its value, photo, location, label, warranty and date.
    assert r["summary"]["missing"]["hasValue"] == 1
    assert r["summary"]["missing"]["hasWarranty"] == 1
    assert r["items"][0]["missingFields"] == [
        "hasValue", "hasPhoto", "hasLocation", "hasLabel", "hasWarranty", "hasPurchaseDate",
    ]


def test_stale_report_lists_expired_warranty(auth_client, app, gid):
    with app.app_context():
        db.session.add(Item(name="Old Drill", purchase_price=50, group_id=gid,
                            warranty_expires=utcnow() - timedelta(days=10)))
        db.session.commit()

    r = auth_client.get("/api/v1/reports/stale").get_json()

    assert r["summary"]["staleCount"] == 1
    assert r["summary"]["warranty"]["expired"] == 1
    assert r["items"][0]["warrantyStatus"] == "expired"


def test_registry_every_report_builds_and_exports(auth_client):
    """Registry-wide sweep: every registered report builds a payload, and any
    report that declares CSV columns exports exactly those columns."""
    from app.api.reports_registry import REPORTS

    for spec in REPORTS:
        # Iterate the registry: each registered report resolves and builds.
        r = auth_client.get(f"/api/v1/reports/{spec.id}")
        assert r.status_code == 200, f"registered report {spec.id!r} failed to build"
        payload = r.get_json()
        assert isinstance(payload, dict)
        assert payload.get("generatedAt")
        assert payload.get("currency")

        if spec.csv_columns is None:
            # No export declared yet for this report — nothing to export.
            continue
        assert spec.csv_columns, f"report {spec.id!r} declares no CSV columns"
        cr = auth_client.get(f"/api/v1/reports/{spec.id}.csv")
        assert cr.status_code == 200
        assert "text/csv" in cr.content_type
        rows = list(csv.reader([cr.get_data(as_text=True)]))
        assert rows and list(rows[0]) == list(spec.csv_columns)


def test_registry_failing_builder_surfaces_and_stays_listed(auth_client, app, monkeypatch):
    """A failing builder must surface as a 500 — and stay a registered report."""
    from app.api.reports_registry import REPORTS

    spec = next(s for s in REPORTS if s.id == "inventory")

    def _boom(db, group_id):
        raise RuntimeError("report builder exploded")

    monkeypatch.setattr(spec, "build", _boom)
    app.config["PROPAGATE_EXCEPTIONS"] = False

    idx = auth_client.get("/api/v1/reports")
    assert idx.status_code == 200
    assert any(e["id"] == "inventory" for e in idx.get_json())

    r = auth_client.get("/api/v1/reports/inventory")
    assert r.status_code == 500
