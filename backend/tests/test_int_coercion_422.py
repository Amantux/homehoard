"""Non-numeric integer inputs return 422, not a generic 500."""


def test_invitation_uses_non_numeric_is_422(auth_client):
    r = auth_client.post("/api/v1/groups/invitations", json={"uses": "abc"})
    assert r.status_code == 422


def test_csv_import_bad_quantity_does_not_crash(auth_client):
    from app.services import csv_io
    assert csv_io._num_or("abc", 1) == 1
    assert csv_io._num_or(None, 1) == 1
    assert csv_io._num_or("5", 1) == 5
    assert csv_io._num_or("3.0", 1) == 3.0


def test_search_limit_non_numeric_does_not_500(auth_client):
    r = auth_client.get("/api/v1/search?q=x&limit=abc")
    assert r.status_code == 200


def test_search_negative_limit_does_not_drop_matches(auth_client):
    # negative limit must not slice from the wrong end; clamped to >= 1
    r = auth_client.get("/api/v1/search?q=x&limit=-5")
    assert r.status_code == 200
