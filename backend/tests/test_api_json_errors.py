"""P7: HTTP errors under /api/ come back as JSON, not Werkzeug's HTML page."""
import pytest


def _bad_json(c):
    return c.post("/api/v1/bins", data="{not json",
                  content_type="application/json")


def _wrong_method(c):
    return c.patch("/api/v1/bins")


def _abort_422(c):
    return c.post("/api/v1/items", json={"name": "Junk", "quantity": "abc"})


@pytest.mark.parametrize("call,status", [
    (_bad_json, 400), (_wrong_method, 405), (_abort_422, 422)])
def test_api_http_errors_are_json(auth_client, call, status):
    r = call(auth_client)
    assert r.status_code == status
    assert r.is_json, r.data[:200]
    body = r.get_json()
    assert body["error"] and "requestId" in body
    assert b"<html" not in r.data.lower() and b"<!doctype" not in r.data.lower()


def test_405_keeps_allow_header(auth_client):
    r = _wrong_method(auth_client)
    assert "GET" in r.headers.get("Allow", "")


def test_422_returns_the_curated_description(auth_client):
    assert _abort_422(auth_client).get_json()["error"] == "quantity must be a number"
