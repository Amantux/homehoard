"""Home-inventory valuation/insurance report."""
from datetime import timedelta
from decimal import Decimal

from app.extensions import db
from app.models import Attachment, Document, Group, Item, Label, Location, utcnow


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


def test_inventory_report_completeness(app, auth_client, gid):

    with app.app_context():
        loc = Location(name="Garage", group_id=gid)
        db.session.add(loc)
        db.session.flush()
        lbl = Label(name="Tools", group_id=gid)
        db.session.add(lbl)
        db.session.flush()

        def _photo(it):
            # A real primary attachment, so the item's photo key fact counts as held.
            doc = Document(title=f"{it.name}.png", path=f"attachments/{it.name}.png", group_id=gid)
            db.session.add(doc)
            db.session.flush()
            db.session.add(Attachment(type="photo", primary=True, item_id=it.id, document_id=doc.id))

        # Value missing: a zero price means the line value is zero — nothing valued.
        no_value = Item(name="NoValue", purchase_price=Decimal("0.00"), quantity=1,
                        location_id=loc.id, group_id=gid,
                        warranty_expires=utcnow() + timedelta(days=30),
                        purchase_date=utcnow() - timedelta(days=5))
        db.session.add(no_value)
        no_value.labels.append(lbl)
        _photo(no_value)

        # Photo missing: no attachment on the item.
        no_photo = Item(name="NoPhoto", purchase_price=Decimal("20.00"), quantity=1,
                        location_id=loc.id, group_id=gid,
                        warranty_expires=utcnow() + timedelta(days=30),
                        purchase_date=utcnow() - timedelta(days=5))
        db.session.add(no_photo)
        no_photo.labels.append(lbl)

        # Location missing: nothing placed it.
        no_location = Item(name="NoLocation", purchase_price=Decimal("30.00"), quantity=1,
                           group_id=gid, warranty_expires=utcnow() + timedelta(days=30),
                           purchase_date=utcnow() - timedelta(days=5))
        db.session.add(no_location)
        no_location.labels.append(lbl)
        _photo(no_location)

        # Label missing: no labels on the item.
        no_label = Item(name="NoLabel", purchase_price=Decimal("40.00"), quantity=1,
                        location_id=loc.id, group_id=gid,
                        warranty_expires=utcnow() + timedelta(days=30),
                        purchase_date=utcnow() - timedelta(days=5))
        db.session.add(no_label)
        _photo(no_label)

        # Warranty date missing: no warranty on file.
        no_warranty = Item(name="NoWarranty", purchase_price=Decimal("50.00"), quantity=1,
                           location_id=loc.id, group_id=gid,
                           purchase_date=utcnow() - timedelta(days=5))
        db.session.add(no_warranty)
        no_warranty.labels.append(lbl)
        _photo(no_warranty)

        # Purchase date missing: nothing bought-recorded on the item.
        no_purchase_date = Item(name="NoPurchaseDate", purchase_price=Decimal("60.00"), quantity=1,
                                location_id=loc.id, group_id=gid,
                                warranty_expires=utcnow() + timedelta(days=30))
        db.session.add(no_purchase_date)
        no_purchase_date.labels.append(lbl)
        _photo(no_purchase_date)

        db.session.commit()
        no_value_id, no_photo_id = no_value.id, no_photo.id
        no_location_id, no_label_id = no_location.id, no_label.id
        no_warranty_id, no_purchase_date_id = no_warranty.id, no_purchase_date.id

    r = auth_client.get("/api/v1/reports/inventory").get_json()
    s = r["summary"]
    comp = s["completeness"]

    by_name = {it["name"]: it for it in r["items"]}
    assert set(by_name) == {"NoValue", "NoPhoto", "NoLocation", "NoLabel", "NoWarranty", "NoPurchaseDate"}

    # Per-item flags: the gap fixture is missing exactly its own key fact, and
    # holds the others the report treats as the shape of a complete item.
    nv = by_name["NoValue"]["completeness"]
    assert nv["value"] is False and nv["photo"] is True and nv["location"] is True
    assert nv["label"] is True and nv["warrantyDate"] is True and nv["purchaseDate"] is True

    np_ = by_name["NoPhoto"]["completeness"]
    assert np_["value"] is True and np_["photo"] is False and np_["location"] is True
    assert np_["label"] is True and np_["warrantyDate"] is True and np_["purchaseDate"] is True

    nloc = by_name["NoLocation"]["completeness"]
    assert nloc["value"] is True and nloc["photo"] is True and nloc["location"] is False
    assert nloc["label"] is True and nloc["warrantyDate"] is True and nloc["purchaseDate"] is True

    nlbl = by_name["NoLabel"]["completeness"]
    assert nlbl["value"] is True and nlbl["photo"] is True and nlbl["location"] is True
    assert nlbl["label"] is False and nlbl["warrantyDate"] is True and nlbl["purchaseDate"] is True

    nwarr = by_name["NoWarranty"]["completeness"]
    assert nwarr["value"] is True and nwarr["photo"] is True and nwarr["location"] is True
    assert nwarr["label"] is True and nwarr["warrantyDate"] is False and nwarr["purchaseDate"] is True

    npur = by_name["NoPurchaseDate"]["completeness"]
    assert npur["value"] is True and npur["photo"] is True and npur["location"] is True
    assert npur["label"] is True and npur["warrantyDate"] is True and npur["purchaseDate"] is False

    # Per-field missing counts: exactly one gap fixture per key fact, pointing at
    # the item that is missing it.
    assert comp["value"]["count"] == 1 and comp["value"]["items"] == [no_value_id]
    assert comp["photo"]["count"] == 1 and comp["photo"]["items"] == [no_photo_id]
    assert comp["location"]["count"] == 1 and comp["location"]["items"] == [no_location_id]
    assert comp["label"]["count"] == 1 and comp["label"]["items"] == [no_label_id]
    assert comp["warrantyDate"]["count"] == 1 and comp["warrantyDate"]["items"] == [no_warranty_id]
    assert comp["purchaseDate"]["count"] == 1 and comp["purchaseDate"]["items"] == [no_purchase_date_id]
