def test_search_where_path(auth_client):
    garage = auth_client.post("/api/v1/locations", json={"name": "Garage"}).get_json()
    shelf = auth_client.post(
        "/api/v1/locations", json={"name": "Shelf", "parentId": garage["id"]}
    ).get_json()
    b = auth_client.post(
        "/api/v1/bins", json={"name": "Bin A", "locationId": shelf["id"]}
    ).get_json()
    auth_client.post("/api/v1/items", json={"name": "Drill", "binId": b["id"]})
    auth_client.post("/api/v1/items", json={"name": "Hammer", "locationId": shelf["id"]})

    drill = auth_client.get("/api/v1/search?q=drill").get_json()["results"][0]
    assert drill["where"] == "Bin A · Garage › Shelf"

    hammer = auth_client.get("/api/v1/search?q=hammer").get_json()["results"][0]
    assert hammer["where"] == "Garage › Shelf"


def test_search_matches_manufacturer(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Widget"}).get_json()
    auth_client.put(
        f"/api/v1/items/{item['id']}",
        json={"name": "Widget", "manufacturer": "Acme"},
    )
    res = auth_client.get("/api/v1/search?q=acme").get_json()
    assert res["total"] == 1
    assert res["results"][0]["name"] == "Widget"


def test_barcode_registered_resolves_to_item(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Cereal"}).get_json()
    auth_client.post(
        "/api/v1/qr-tags",
        json={"kind": "item", "targetId": item["id"], "source": "external",
              "code": "111222333444"},
    )
    r = auth_client.get("/api/v1/barcode/111222333444").get_json()
    assert r["status"] == "registered"
    assert r["kind"] == "item"
    assert r["target"]["id"] == item["id"]


def test_search_matches_bins_and_locations(auth_client):
    loc = auth_client.post("/api/v1/locations", json={"name": "Garage"}).get_json()
    auth_client.post("/api/v1/bins", json={"name": "Garage Overflow", "locationId": loc["id"]})
    res = auth_client.get("/api/v1/search?q=garage").get_json()["results"]
    types = {r["type"] for r in res}
    assert "location" in types and "bin" in types
    loc_hit = next(r for r in res if r["type"] == "location")
    assert loc_hit["name"] == "Garage"


def test_barcode_bin_shows_contents(auth_client):
    b = auth_client.post("/api/v1/bins", json={"name": "Parts"}).get_json()
    auth_client.post("/api/v1/items", json={"name": "Bolt", "binId": b["id"]})
    auth_client.post(
        "/api/v1/qr-tags",
        json={"kind": "bin", "targetId": b["id"], "source": "external", "code": "BINCODE1"},
    )
    r = auth_client.get("/api/v1/barcode/BINCODE1").get_json()
    assert r["status"] == "registered"
    assert r["kind"] == "bin"
    assert r["target"]["items"][0]["name"] == "Bolt"


def test_barcode_not_found_no_outbound(auth_client):
    r = auth_client.get("/api/v1/barcode/999888777666").get_json()
    assert r["status"] == "not_found"
    assert "product" not in r


def test_search_requires_auth(client):
    assert client.get("/api/v1/search?q=x").status_code == 401
