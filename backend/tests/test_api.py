import io


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
