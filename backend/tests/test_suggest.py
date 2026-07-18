"""Placement suggestions: put an item where similar items already live."""


def _mk_location(auth_client, name):
    return auth_client.post("/api/v1/locations", json={"name": name}).get_json()


def _mk_bin(auth_client, name, location_id=None):
    return auth_client.post(
        "/api/v1/bins", json={"name": name, "locationId": location_id}
    ).get_json()


def _mk_item(auth_client, name, **kw):
    return auth_client.post("/api/v1/items", json={"name": name, **kw}).get_json()


def test_suggests_bin_where_similar_items_live(auth_client):
    garage = _mk_location(auth_client, "Garage")
    tool_bin = _mk_bin(auth_client, "Tool Bin", garage["id"])
    _mk_item(auth_client, "Cordless drill", binId=tool_bin["id"])
    _mk_item(auth_client, "Drill bits", binId=tool_bin["id"])
    # An unrelated item elsewhere shouldn't outrank the tool bin.
    kitchen = _mk_location(auth_client, "Kitchen")
    _mk_item(auth_client, "Spatula", locationId=kitchen["id"])

    res = auth_client.get("/api/v1/items/suggest-placement?name=hammer drill").get_json()
    sugg = res["suggestions"]
    assert sugg, "expected at least one suggestion"
    top = sugg[0]
    assert top["type"] == "bin" and top["id"] == tool_bin["id"]
    assert top["basis"] == "similar"
    assert top["count"] == 2
    assert "Cordless drill" in top["samples"]


def test_falls_back_to_popular_when_nothing_similar(auth_client):
    garage = _mk_location(auth_client, "Garage")
    tool_bin = _mk_bin(auth_client, "Tool Bin", garage["id"])
    _mk_item(auth_client, "Wrench", binId=tool_bin["id"])
    _mk_item(auth_client, "Pliers", binId=tool_bin["id"])

    # Nothing named like "saxophone" exists → popular fallback (the tool bin).
    res = auth_client.get(
        "/api/v1/items/suggest-placement?name=saxophone"
    ).get_json()["suggestions"]
    assert res
    assert res[0]["basis"] == "popular"
    assert res[0]["id"] == tool_bin["id"]


def test_empty_inventory_returns_no_suggestions(auth_client):
    res = auth_client.get(
        "/api/v1/items/suggest-placement?name=anything"
    ).get_json()
    assert res == {"suggestions": []}


def test_suggest_placement_requires_auth(client):
    assert client.get("/api/v1/items/suggest-placement?name=x").status_code == 401


def test_suggestions_are_group_isolated(auth_client, app):
    garage = _mk_location(auth_client, "Garage")
    tool_bin = _mk_bin(auth_client, "Tool Bin", garage["id"])
    _mk_item(auth_client, "Cordless drill", binId=tool_bin["id"])

    other = app.test_client()
    other.post("/api/v1/users/register",
               json={"email": "o@t.com", "password": "password", "name": "O"})
    tok = other.post("/api/v1/users/login",
                     json={"username": "o@t.com", "password": "password"}).get_json()["token"]
    other.environ_base["HTTP_AUTHORIZATION"] = tok
    # Group B sees none of group A's placements.
    assert other.get(
        "/api/v1/items/suggest-placement?name=drill"
    ).get_json() == {"suggestions": []}
