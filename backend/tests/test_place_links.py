"""The item's location/bin must carry an `id`, because the UI links to it.

The item page, the item cards and the list all render the place as a link to
/locations/<id> or /bins/<id>. Those ids come from the serializer, and the
frontend cannot enforce their presence — drop one and every link silently
becomes "/locations/undefined", which looks fine in review and 404s for the user.
"""


def _place(c):
    loc = c.post("/api/v1/locations", json={"name": "Garage"}).get_json()
    b = c.post("/api/v1/bins", json={"name": "Crate",
                                     "locationId": loc["id"]}).get_json()
    return loc, b


def test_item_detail_carries_ids_for_its_location_and_bin(auth_client):
    loc, b = _place(auth_client)
    item = auth_client.post("/api/v1/items",
                            json={"name": "Drill", "binId": b["id"]}).get_json()

    got = auth_client.get(f"/api/v1/items/{item['id']}").get_json()

    assert got["location"]["id"] == loc["id"]
    assert got["bin"]["id"] == b["id"]


def test_each_placement_carries_ids_too(auth_client):
    """The placements list links every row, not just the primary one."""
    loc, b = _place(auth_client)
    item = auth_client.post("/api/v1/items",
                            json={"name": "Drill", "binId": b["id"]}).get_json()

    holdings = auth_client.get(f"/api/v1/items/{item['id']}").get_json()["holdings"]

    assert holdings, "an item should start with one placement"
    assert holdings[0]["bin"]["id"] == b["id"]
    assert holdings[0]["location"]["id"] == loc["id"]


def test_the_items_list_carries_ids(auth_client):
    """The grid cards and the table both link from the list."""
    loc, b = _place(auth_client)
    auth_client.post("/api/v1/items", json={"name": "Drill", "binId": b["id"]})
    auth_client.post("/api/v1/items", json={"name": "Rake", "locationId": loc["id"]})

    rows = auth_client.get("/api/v1/items").get_json()["items"]

    by_name = {r["name"]: r for r in rows}
    assert by_name["Drill"]["bin"]["id"] == b["id"]
    assert by_name["Rake"]["location"]["id"] == loc["id"]


def test_the_linked_places_actually_resolve(auth_client):
    """A link is only useful if the target loads — this is the round trip the
    user makes when they click it."""
    loc, b = _place(auth_client)
    item = auth_client.post("/api/v1/items",
                            json={"name": "Drill", "binId": b["id"]}).get_json()
    got = auth_client.get(f"/api/v1/items/{item['id']}").get_json()

    assert auth_client.get(f"/api/v1/bins/{got['bin']['id']}").status_code == 200
    assert auth_client.get(
        f"/api/v1/locations/{got['location']['id']}").status_code == 200
