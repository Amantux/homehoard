"""Nested locations: sites → sub-locations, with cycle/cross-group guards."""


def _loc(auth_client, name, parent_id=None):
    r = auth_client.post(
        "/api/v1/locations", json={"name": name, "parentId": parent_id}
    )
    return r


def _other_group_client(app):
    c = app.test_client()
    c.post("/api/v1/users/register",
           json={"email": "o@t.com", "password": "password", "name": "O"})
    tok = c.post("/api/v1/users/login",
                 json={"username": "o@t.com", "password": "password"}).get_json()["token"]
    c.environ_base["HTTP_AUTHORIZATION"] = tok
    return c


def test_nesting_creates_child_under_parent(auth_client):
    site = _loc(auth_client, "Lake House").get_json()
    room = _loc(auth_client, "Garage", site["id"])
    assert room.status_code == 201
    assert room.get_json()["parent"]["id"] == site["id"]


def test_location_path_returns_full_ancestor_chain(auth_client):
    site = _loc(auth_client, "Lake House").get_json()
    garage = _loc(auth_client, "Garage", site["id"]).get_json()
    shelf = _loc(auth_client, "Shelf A", garage["id"]).get_json()
    path = auth_client.get(f"/api/v1/locations/{shelf['id']}/path").get_json()
    assert [p["name"] for p in path] == ["Lake House", "Garage", "Shelf A"]


def test_reparent_to_self_rejected(auth_client):
    site = _loc(auth_client, "Storage Locker").get_json()
    r = auth_client.put(f"/api/v1/locations/{site['id']}", json={"parentId": site["id"]})
    assert r.status_code == 422


def test_reparent_into_own_descendant_rejected(auth_client):
    site = _loc(auth_client, "Rental").get_json()
    child = _loc(auth_client, "Bedroom", site["id"]).get_json()
    # Moving the site under its own child would orphan the subtree.
    r = auth_client.put(f"/api/v1/locations/{site['id']}", json={"parentId": child["id"]})
    assert r.status_code == 422
    # The site is untouched.
    assert auth_client.get(f"/api/v1/locations/{site['id']}").get_json()["parent"] is None


def test_create_rejects_cross_group_parent(auth_client, app):
    mine = _loc(auth_client, "My Site").get_json()
    other = _other_group_client(app)
    r = other.post("/api/v1/locations", json={"name": "Sneaky", "parentId": mine["id"]})
    assert r.status_code == 422


def test_reparent_rejects_cross_group_parent(auth_client, app):
    mine = _loc(auth_client, "My Site").get_json()
    other = _other_group_client(app)
    theirs = other.post("/api/v1/locations", json={"name": "Their Site"}).get_json()
    # Group B cannot parent its location under group A's location.
    r = other.put(f"/api/v1/locations/{theirs['id']}", json={"parentId": mine["id"]})
    assert r.status_code == 422
