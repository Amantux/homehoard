"""Non-numeric integer inputs return 422, not a generic 500."""


def test_invitation_uses_non_numeric_is_422(auth_client):
    r = auth_client.post("/api/v1/groups/invitations", json={"uses": "abc"})
    assert r.status_code == 422


def test_csv_import_bad_quantity_does_not_crash(auth_client):
    from app.services import csv_io
    assert csv_io._int_or("abc", 1) == 1
    assert csv_io._int_or(None, 1) == 1
    assert csv_io._int_or("5", 1) == 5
    assert csv_io._int_or("3.0", 1) == 3
