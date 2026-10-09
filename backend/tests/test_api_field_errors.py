"""P17: abort_fields() -> 422 JSON carrying per-field messages."""
import pytest

from app.api._validation import abort_fields


@pytest.fixture()
def fields_route(app):
    # Registered before auth_client's first request (Flask forbids adding
    # routes after the app has handled one).
    def boom():
        abort_fields({"name": "Name is required"}, "Fix the highlighted field.")

    app.add_url_rule("/api/v1/_test/fields", "test_fields", boom, methods=["POST"])


def test_abort_fields_body(fields_route, auth_client):
    r = auth_client.post("/api/v1/_test/fields", json={})
    assert r.status_code == 422
    body = r.get_json()
    assert body["error"] == "Fix the highlighted field."
    assert body["fields"] == {"name": "Name is required"}
    assert "requestId" in body
    assert set(body) == {"error", "requestId", "fields"}


def test_plain_422_has_no_fields_key(auth_client):
    r = auth_client.post("/api/v1/items", json={"name": "Junk", "quantity": "abc"})
    assert r.status_code == 422
    assert "fields" not in r.get_json()
