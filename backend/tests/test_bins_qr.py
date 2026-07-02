def _location(c, name="Garage"):
    return c.post("/api/v1/locations", json={"name": name}).get_json()


def test_bin_holds_items(auth_client):
    loc = _location(auth_client)
    b = auth_client.post(
        "/api/v1/bins", json={"name": "Bin A", "locationId": loc["id"]}
    ).get_json()
    assert b["location"]["name"] == "Garage"

    item = auth_client.post(
        "/api/v1/items", json={"name": "Screws", "binId": b["id"]}
    ).get_json()
    assert item["bin"]["name"] == "Bin A"

    full = auth_client.get(f"/api/v1/bins/{b['id']}").get_json()
    assert full["itemCount"] == 1
    assert full["items"][0]["name"] == "Screws"


def test_location_lists_bins(auth_client):
    loc = _location(auth_client)
    auth_client.post("/api/v1/bins", json={"name": "Bin A", "locationId": loc["id"]})
    detail = auth_client.get(f"/api/v1/locations/{loc['id']}").get_json()
    assert detail["bins"][0]["name"] == "Bin A"


def test_add_remove_item_to_bin(auth_client):
    loc = _location(auth_client)
    b = auth_client.post(
        "/api/v1/bins", json={"name": "B", "locationId": loc["id"]}
    ).get_json()
    item = auth_client.post("/api/v1/items", json={"name": "Tape"}).get_json()

    auth_client.put(f"/api/v1/bins/{b['id']}/items/{item['id']}")
    assert auth_client.get(f"/api/v1/bins/{b['id']}").get_json()["itemCount"] == 1
    # item inherits bin location
    assert auth_client.get(f"/api/v1/items/{item['id']}").get_json()["location"]["id"] == loc["id"]

    auth_client.delete(f"/api/v1/bins/{b['id']}/items/{item['id']}")
    assert auth_client.get(f"/api/v1/bins/{b['id']}").get_json()["itemCount"] == 0


def test_moving_bin_moves_its_items(auth_client):
    garage = _location(auth_client, "Garage")
    attic = _location(auth_client, "Attic")
    b = auth_client.post(
        "/api/v1/bins", json={"name": "Box", "locationId": garage["id"]}
    ).get_json()
    item = auth_client.post(
        "/api/v1/items", json={"name": "Cable", "binId": b["id"]}
    ).get_json()

    # Move the bin to the attic; the item should follow.
    auth_client.put(f"/api/v1/bins/{b['id']}", json={"locationId": attic["id"]})
    got = auth_client.get(f"/api/v1/items/{item['id']}").get_json()
    assert got["location"]["id"] == attic["id"]
    assert got["bin"]["id"] == b["id"]


def test_delete_bin_keeps_items(auth_client):
    b = auth_client.post("/api/v1/bins", json={"name": "B"}).get_json()
    item = auth_client.post(
        "/api/v1/items", json={"name": "Keep", "binId": b["id"]}
    ).get_json()
    auth_client.delete(f"/api/v1/bins/{b['id']}")
    got = auth_client.get(f"/api/v1/items/{item['id']}").get_json()
    assert got["bin"] is None


def test_multiple_qr_per_target(auth_client):
    b = auth_client.post("/api/v1/bins", json={"name": "B"}).get_json()
    t1 = auth_client.post(
        "/api/v1/qr-tags", json={"kind": "bin", "targetId": b["id"], "description": "lid"}
    ).get_json()
    auth_client.post(
        "/api/v1/qr-tags", json={"kind": "bin", "targetId": b["id"], "description": "side"}
    )
    tags = auth_client.get(f"/api/v1/qr-tags?kind=bin&targetId={b['id']}").get_json()
    assert len(tags) == 2
    assert t1["token"]
    assert t1["scanUrl"].endswith("/#/t/" + t1["token"])


def test_qr_resolve_and_image(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Gadget"}).get_json()
    tag = auth_client.post(
        "/api/v1/qr-tags", json={"kind": "item", "targetId": item["id"]}
    ).get_json()

    resolved = auth_client.get(f"/api/v1/qr-tags/resolve/{tag['token']}").get_json()
    assert resolved["kind"] == "item"
    assert resolved["target"]["id"] == item["id"]

    img = auth_client.get(f"/api/v1/qr-tags/{tag['id']}/image")
    assert img.status_code == 200
    assert img.mimetype == "image/png"
    assert img.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_qr_ingress_url(auth_client):
    loc = _location(auth_client, "Shed")
    tag = auth_client.post(
        "/api/v1/qr-tags",
        json={"kind": "location", "targetId": loc["id"]},
        headers={
            "X-Ingress-Path": "/api/hassio_ingress/tok",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "ha.local",
        },
    ).get_json()
    assert tag["scanUrl"] == f"https://ha.local/api/hassio_ingress/tok/#/t/{tag['token']}"


def test_register_own_barcode(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Cereal"}).get_json()
    r = auth_client.post(
        "/api/v1/qr-tags",
        json={"kind": "item", "targetId": item["id"], "source": "external",
              "code": "036000291452", "codeFormat": "ean13"},
    )
    assert r.status_code == 201
    tag = r.get_json()
    assert tag["source"] == "external"
    assert tag["code"] == "036000291452"

    # Scanning the physical barcode resolves to the item.
    res = auth_client.get("/api/v1/qr-tags/resolve/036000291452")
    assert res.status_code == 200
    assert res.get_json()["target"]["id"] == item["id"]


def test_duplicate_external_code_rejected(auth_client):
    a = auth_client.post("/api/v1/items", json={"name": "A"}).get_json()
    b = auth_client.post("/api/v1/items", json={"name": "B"}).get_json()
    auth_client.post("/api/v1/qr-tags", json={
        "kind": "item", "targetId": a["id"], "source": "external", "code": "DUP1"})
    dup = auth_client.post("/api/v1/qr-tags", json={
        "kind": "item", "targetId": b["id"], "source": "external", "code": "DUP1"})
    assert dup.status_code == 409


def test_external_requires_code(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "X"}).get_json()
    r = auth_client.post("/api/v1/qr-tags", json={
        "kind": "item", "targetId": item["id"], "source": "external"})
    assert r.status_code == 422


def test_resolve_unknown_returns_code(auth_client):
    r = auth_client.get("/api/v1/qr-tags/resolve/nosuchcode")
    assert r.status_code == 404
    assert r.get_json()["code"] == "nosuchcode"


def test_qr_invalid_kind(auth_client):
    assert (
        auth_client.post(
            "/api/v1/qr-tags", json={"kind": "nope", "targetId": "x"}
        ).status_code
        == 422
    )


def test_qr_group_scoped(client):
    def make(email):
        client.post(
            "/api/v1/users/register",
            json={"email": email, "password": "pw12345", "name": "X"},
        )
        return client.post(
            "/api/v1/users/login", json={"username": email, "password": "pw12345"}
        ).get_json()["token"]

    a = make("qa@x.com")
    b = make("qb@x.com")
    item = client.post(
        "/api/v1/items", json={"name": "Mine"}, headers={"Authorization": a}
    ).get_json()
    tag = client.post(
        "/api/v1/qr-tags",
        json={"kind": "item", "targetId": item["id"]},
        headers={"Authorization": a},
    ).get_json()
    # user b cannot resolve user a's tag
    assert (
        client.get(
            f"/api/v1/qr-tags/resolve/{tag['token']}", headers={"Authorization": b}
        ).status_code
        == 404
    )


def test_item_field_time_type(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Timed"}).get_json()
    updated = auth_client.put(
        f"/api/v1/items/{item['id']}",
        json={
            "name": "Timed",
            "fields": [
                {"name": "Calibrated", "type": "time", "timeValue": "2026-01-15T00:00:00"}
            ],
        },
    ).get_json()
    assert updated["fields"][0]["type"] == "time"
    assert updated["fields"][0]["timeValue"].startswith("2026-01-15")
