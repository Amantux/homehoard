"""API token (long-lived key) lifecycle and auth."""


def _make_token(auth_client, name="HA"):
    r = auth_client.post("/api/v1/tokens", json={"name": name})
    assert r.status_code == 201
    return r.get_json()


def test_create_returns_raw_once_and_lists_without_it(auth_client):
    created = _make_token(auth_client, "Home Assistant")
    assert created["token"].startswith("hh_")
    assert created["name"] == "Home Assistant"
    assert created["hint"] and created["hint"] in created["token"]

    listed = auth_client.get("/api/v1/tokens").get_json()
    assert len(listed) == 1
    # The raw token is never returned again.
    assert "token" not in listed[0]
    assert listed[0]["id"] == created["id"]


def test_api_token_authenticates_protected_endpoints(app, auth_client):
    raw = _make_token(auth_client)["token"]
    # A fresh client with no JWT — only the API token.
    fresh = app.test_client()
    r = fresh.get("/api/v1/ha/summary", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200
    assert "totals" in r.get_json()
    # Search (used by the HA voice intent) also works with the token.
    assert fresh.get(
        "/api/v1/search?q=x", headers={"Authorization": f"Bearer {raw}"}
    ).status_code == 200


def test_bad_api_token_is_unauthorized(app):
    fresh = app.test_client()
    r = fresh.get(
        "/api/v1/items", headers={"Authorization": "Bearer hh_notarealtoken"}
    )
    assert r.status_code == 401


def test_revoked_token_stops_working(app, auth_client):
    created = _make_token(auth_client)
    raw = created["token"]
    fresh = app.test_client()
    assert fresh.get(
        "/api/v1/ha/summary", headers={"Authorization": f"Bearer {raw}"}
    ).status_code == 200

    assert auth_client.delete(f"/api/v1/tokens/{created['id']}").status_code == 204
    assert fresh.get(
        "/api/v1/ha/summary", headers={"Authorization": f"Bearer {raw}"}
    ).status_code == 401
    assert auth_client.get("/api/v1/tokens").get_json() == []


def _second_group_client(app):
    """A logged-in client in a different group (registration creates a group)."""
    c = app.test_client()
    c.post(
        "/api/v1/users/register",
        json={"email": "other@t.com", "password": "password", "name": "Other"},
    )
    token = c.post(
        "/api/v1/users/login",
        json={"username": "other@t.com", "password": "password"},
    ).get_json()["token"]
    c.environ_base["HTTP_AUTHORIZATION"] = token
    return c


def test_tokens_are_group_isolated(app, auth_client):
    """A user in another group can neither see nor revoke this group's token."""
    created = _make_token(auth_client, "Group A token")
    other = _second_group_client(app)

    # Not visible to the other group.
    assert other.get("/api/v1/tokens").get_json() == []
    # Cannot be revoked cross-group.
    assert other.delete(f"/api/v1/tokens/{created['id']}").status_code == 404
    # Still works for group A after the failed cross-group revoke.
    assert len(auth_client.get("/api/v1/tokens").get_json()) == 1
    raw = created["token"]
    assert app.test_client().get(
        "/api/v1/ha/summary", headers={"Authorization": f"Bearer {raw}"}
    ).status_code == 200


def test_last_used_recorded_on_use(app, auth_client):
    raw = _make_token(auth_client)["token"]
    assert auth_client.get("/api/v1/tokens").get_json()[0]["lastUsedAt"] is None
    fresh = app.test_client()
    fresh.get("/api/v1/ha/summary", headers={"Authorization": f"Bearer {raw}"})
    assert auth_client.get("/api/v1/tokens").get_json()[0]["lastUsedAt"] is not None
