import io
from datetime import timedelta
from decimal import Decimal

from app.extensions import db
from app.models import Attachment, Document, Item, Label, Location, utcnow


def test_status_public(client):
    r = client.get("/api/v1/status")
    assert r.status_code == 200
    assert r.get_json()["health"] is True


def test_requires_auth(client):
    assert client.get("/api/v1/items").status_code == 401


def test_register_login_self(client):
    assert (
        client.post(
            "/api/v1/users/register",
            json={"email": "a@b.com", "password": "pw123456", "name": "A"},
        ).status_code
        == 201
    )
    tok = client.post(
        "/api/v1/users/login", json={"username": "a@b.com", "password": "pw123456"}
    ).get_json()["token"]
    r = client.get("/api/v1/users/self", headers={"Authorization": tok})
    assert r.get_json()["item"]["email"] == "a@b.com"


def test_bad_login(client):
    client.post(
        "/api/v1/users/register",
        json={"email": "a@b.com", "password": "pw123456", "name": "A"},
    )
    assert (
        client.post(
            "/api/v1/users/login", json={"username": "a@b.com", "password": "wrong"}
        ).status_code
        == 401
    )


def test_item_crud(auth_client):
    loc = auth_client.post("/api/v1/locations", json={"name": "Garage"}).get_json()
    label = auth_client.post("/api/v1/labels", json={"name": "Tools"}).get_json()
    item = auth_client.post(
        "/api/v1/items",
        json={"name": "Drill", "locationId": loc["id"], "labelIds": [label["id"]]},
    ).get_json()
    assert item["assetId"] == "000-001"
    assert item["labels"][0]["name"] == "Tools"

    updated = auth_client.put(
        f"/api/v1/items/{item['id']}",
        json={"name": "Drill", "purchasePrice": 99.5, "quantity": 2},
    ).get_json()
    assert updated["purchasePrice"] == 99.5

    listing = auth_client.get("/api/v1/items").get_json()
    assert listing["total"] == 1

    assert auth_client.delete(f"/api/v1/items/{item['id']}").status_code == 204
    assert auth_client.get("/api/v1/items").get_json()["total"] == 0


def test_group_scoping(client):
    # Two separate users in separate groups cannot see each other's items.
    def make(email):
        client.post(
            "/api/v1/users/register",
            json={"email": email, "password": "pw123456", "name": "X"},
        )
        return client.post(
            "/api/v1/users/login", json={"username": email, "password": "pw123456"}
        ).get_json()["token"]

    a = make("a@x.com")
    b = make("b@x.com")
    client.post("/api/v1/items", json={"name": "Secret"}, headers={"Authorization": a})
    assert client.get("/api/v1/items", headers={"Authorization": b}).get_json()[
        "total"
    ] == 0


def test_search_filter(auth_client):
    auth_client.post("/api/v1/items", json={"name": "Hammer"})
    auth_client.post("/api/v1/items", json={"name": "Screwdriver"})
    res = auth_client.get("/api/v1/items?q=hammer").get_json()
    assert res["total"] == 1
    assert res["items"][0]["name"] == "Hammer"


def test_items_missing_filter(app, auth_client, gid):
    """?missing=<gap> narrows the item list to the items lacking that key fact.

    The read-side counterpart of the report's per-field missing counts: the
    Report's completeness card links each gap here, so the list filter and the
    report counts have to agree on what "missing" means.

    The fixture mirrors the report's completeness fixture — each item is missing
    exactly its own key fact and holds the others — so a ?missing= query isolates
    a single item per gap instead of sweeping in every item that lacks an
    optional fact (an item with no photo has no photo however many items exist).
    """
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

        no_value = Item(name="NoValue", purchase_price=Decimal("0.00"), quantity=1,
                        location_id=loc.id, group_id=gid,
                        warranty_expires=utcnow() + timedelta(days=30),
                        purchase_date=utcnow() - timedelta(days=5))
        db.session.add(no_value)
        no_value.labels.append(lbl)
        _photo(no_value)

        no_photo = Item(name="NoPhoto", purchase_price=Decimal("20.00"), quantity=1,
                        location_id=loc.id, group_id=gid,
                        warranty_expires=utcnow() + timedelta(days=30),
                        purchase_date=utcnow() - timedelta(days=5))
        db.session.add(no_photo)
        no_photo.labels.append(lbl)

        no_location = Item(name="NoLocation", purchase_price=Decimal("30.00"), quantity=1,
                           group_id=gid, warranty_expires=utcnow() + timedelta(days=30),
                           purchase_date=utcnow() - timedelta(days=5))
        db.session.add(no_location)
        no_location.labels.append(lbl)
        _photo(no_location)

        no_label = Item(name="NoLabel", purchase_price=Decimal("40.00"), quantity=1,
                        location_id=loc.id, group_id=gid,
                        warranty_expires=utcnow() + timedelta(days=30),
                        purchase_date=utcnow() - timedelta(days=5))
        db.session.add(no_label)
        _photo(no_label)

        no_warranty = Item(name="NoWarranty", purchase_price=Decimal("50.00"), quantity=1,
                           location_id=loc.id, group_id=gid,
                           purchase_date=utcnow() - timedelta(days=5))
        db.session.add(no_warranty)
        no_warranty.labels.append(lbl)
        _photo(no_warranty)

        no_purchase_date = Item(name="NoPurchaseDate", purchase_price=Decimal("60.00"), quantity=1,
                                location_id=loc.id, group_id=gid,
                                warranty_expires=utcnow() + timedelta(days=30))
        db.session.add(no_purchase_date)
        no_purchase_date.labels.append(lbl)
        _photo(no_purchase_date)

        db.session.commit()

    cases = [
        ("value", "NoValue"),
        ("photo", "NoPhoto"),
        ("location", "NoLocation"),
        ("label", "NoLabel"),
        ("warrantyDate", "NoWarranty"),
        ("purchaseDate", "NoPurchaseDate"),
    ]
    for gap, name in cases:
        res = auth_client.get(f"/api/v1/items?missing={gap}").get_json()
        assert res["total"] == 1, gap
        assert res["items"][0]["name"] == name, gap


def test_csv_roundtrip(auth_client):
    csv = (
        "HB.name,HB.location,HB.labels,HB.quantity,HB.purchase_price\n"
        "Wrench,Shed,tools;hand,3,12.50\n"
    )
    r = auth_client.post(
        "/api/v1/items/import",
        data={"csv": (io.BytesIO(csv.encode()), "x.csv")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 201
    assert r.get_json()["imported"] == 1

    items = auth_client.get("/api/v1/items").get_json()["items"]
    assert items[0]["name"] == "Wrench"
    assert items[0]["location"]["name"] == "Shed"
    assert {lbl["name"] for lbl in items[0]["labels"]} == {"tools", "hand"}

    export = auth_client.get("/api/v1/items/export").data.decode()
    assert "Wrench" in export and "HB.name" in export


def test_csv_import_unescapes_formula_guard(auth_client):
    # A CSV shaped like our own export: a leading ' guards formula-injection cells
    # (name starting with '-', a negative price). Import must reverse the escaping.
    csv = "HB.name,HB.quantity,HB.purchase_price\n'-40C Probe,2,'-5.00\n"

    r = auth_client.post(
        "/api/v1/items/import",
        data={"csv": (io.BytesIO(csv.encode()), "x.csv")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 201  # '-5.00 did not crash float() parsing

    item = auth_client.get("/api/v1/items").get_json()["items"][0]
    assert item["name"] == "-40C Probe"  # leading quote stripped, lossless
    assert item["purchasePrice"] == -5.0


def test_csv_roundtrips_barcode(auth_client):
    csv = "HB.name,HB.barcode\nDrill,012345678905\n"
    r = auth_client.post(
        "/api/v1/items/import",
        data={"csv": (io.BytesIO(csv.encode()), "x.csv")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 201

    # imported onto the item... (barcode lives on the item detail, not the summary)
    item_id = auth_client.get("/api/v1/items").get_json()["items"][0]["id"]
    item = auth_client.get(f"/api/v1/items/{item_id}").get_json()
    assert item["barcode"] == "012345678905"
    # ...and it survives an export round-trip.
    export = auth_client.get("/api/v1/items/export").data.decode()
    assert "HB.barcode" in export and "012345678905" in export


def test_statistics(auth_client):
    auth_client.post("/api/v1/items", json={"name": "A"})
    auth_client.put(
        f"/api/v1/items/{auth_client.get('/api/v1/items').get_json()['items'][0]['id']}",
        json={"name": "A", "purchasePrice": 10, "quantity": 2},
    )
    stats = auth_client.get("/api/v1/groups/statistics").get_json()
    assert stats["totalItems"] == 1
    assert stats["totalItemPrice"] == 20


def test_location_tree(auth_client):
    parent = auth_client.post("/api/v1/locations", json={"name": "House"}).get_json()
    auth_client.post(
        "/api/v1/locations", json={"name": "Bedroom", "parentId": parent["id"]}
    )
    tree = auth_client.get("/api/v1/locations/tree").get_json()
    assert tree[0]["name"] == "House"
    assert tree[0]["children"][0]["name"] == "Bedroom"


def test_noauth_mode(noauth_app):
    c = noauth_app.test_client()
    # No token required.
    assert c.get("/api/v1/users/self").status_code == 200
    assert c.post("/api/v1/items", json={"name": "Auto"}).status_code == 201
    assert c.get("/api/v1/items").get_json()["total"] == 1


def test_asset_lookup(auth_client):
    auth_client.post("/api/v1/items", json={"name": "AssetItem"})
    r = auth_client.get("/api/v1/assets/000-001")
    assert r.get_json()["total"] == 1


def test_create_item_retries_on_asset_id_collision(auth_client, monkeypatch):
    """When two creates race to the same per-group asset id, the unique index rejects
    the loser and create_item retries onto a free id instead of 500-ing."""
    first = auth_client.post("/api/v1/items", json={"name": "A"}).get_json()

    # Force the allocator to hand out the taken id once, then a free one.
    from app.api import items as items_api
    seq = iter([first["assetId"] and 1, 2])  # 1 is A's id (taken) → collision → retry
    monkeypatch.setattr(items_api, "_next_asset_id", lambda gid: next(seq))

    second = auth_client.post("/api/v1/items", json={"name": "B"})
    assert second.status_code == 201
    assert second.get_json()["assetId"] != first["assetId"]
