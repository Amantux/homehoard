"""Input validation on registration, profile and location writes (P35).

Every rejection is a 422 with a ``fields`` mapping (abort_fields), never a 500,
and the server's synthetic identities (HA ``ha:<id>`` users, the shared
``local@easyinventory`` user) cannot be claimed through the API.
"""
import pytest

H = "/api/v1"


def _register(client, **over):
    body = {"email": "new@example.com", "password": "password123", "name": "New"}
    body.update(over)
    return client.post(f"{H}/users/register", json=body)


@pytest.mark.parametrize("email", ["ha:123", "HA:123", "ha:1@example.com"])
def test_register_rejects_ha_synthetic_email(client, email):
    r = _register(client, email=email)
    assert r.status_code == 422
    assert r.get_json()["fields"] == {"email": "This email address is reserved"}


@pytest.mark.parametrize("email", ["local@easyinventory", " Other@EasyInventory "])
def test_register_rejects_reserved_local_domain(client, email):
    r = _register(client, email=email)
    assert r.status_code == 422
    assert r.get_json()["fields"] == {"email": "This email address is reserved"}


@pytest.mark.parametrize("email", [5, None, "", "no-at-sign", "a@", "@b", "a@b@c", "a b@c.d"])
def test_register_rejects_malformed_email(client, email):
    r = _register(client, email=email)
    assert r.status_code == 422
    assert "email" in r.get_json()["fields"]


@pytest.mark.parametrize("name", [None, "", "   ", 7, ["x"]])
def test_register_requires_name(client, name):
    r = _register(client, name=name)
    assert r.status_code == 422
    assert r.get_json()["fields"] == {"name": "Name is required"}


@pytest.mark.parametrize("raw", ["[]", "[1, 2]", '"str"', "3", "null"])
def test_register_rejects_non_object_body(client, raw):
    r = client.post(f"{H}/users/register", data=raw, content_type="application/json")
    assert r.status_code == 422
    assert r.get_json()["fields"] == {"body": "must be a JSON object"}


def test_register_normalises_valid_email(client):
    r = _register(client, email="  Mixed@Example.COM ")
    assert r.status_code == 201
    assert r.get_json()["email"] == "mixed@example.com"


def test_update_self_non_string_email_is_422_not_500(auth_client):
    r = auth_client.put(f"{H}/users/self", json={"email": 5})
    assert r.status_code == 422
    assert "email" in r.get_json()["fields"]


def test_update_self_rejects_reserved_email(auth_client):
    r = auth_client.put(f"{H}/users/self", json={"email": "ha:999"})
    assert r.status_code == 422
    assert auth_client.get(f"{H}/users/self").get_json()["item"]["email"] == "t@t.com"


def test_update_self_echoing_current_email_is_noop(auth_client):
    r = auth_client.put(f"{H}/users/self", json={"email": "T@t.com", "name": "Renamed"})
    assert r.status_code == 200
    assert r.get_json()["item"]["name"] == "Renamed"


@pytest.mark.parametrize("body", [[], "x"])
def test_update_self_rejects_non_object_body(auth_client, body):
    assert auth_client.put(f"{H}/users/self", json=body).status_code == 422


def test_update_self_null_name_is_422(auth_client):
    r = auth_client.put(f"{H}/users/self", json={"name": None})
    assert r.status_code == 422
    assert r.get_json()["fields"] == {"name": "Name is required"}


def test_location_create_null_name_is_422(auth_client):
    r = auth_client.post(f"{H}/locations", json={"name": None})
    assert r.status_code == 422
    assert r.get_json()["fields"] == {"name": "Name is required"}


def test_location_create_list_body_is_422(auth_client):
    assert auth_client.post(f"{H}/locations", json=[]).status_code == 422


def test_location_update_null_name_is_422(auth_client):
    loc = auth_client.post(f"{H}/locations", json={"name": "Garage"}).get_json()
    r = auth_client.put(f"{H}/locations/{loc['id']}", json={"name": None})
    assert r.status_code == 422
    assert auth_client.get(f"{H}/locations/{loc['id']}").get_json()["name"] == "Garage"


def test_body_without_json_content_type_still_parses(auth_client):
    r = auth_client.post(f"{H}/locations", data='{"name": "Shed"}',
                         content_type="text/plain")
    assert r.status_code == 201


@pytest.mark.parametrize("email", ["\u200bha:1@example.com", "local@easyinventory\u200b",
                                   "\u200dlocal@easyinventory", "ha\ufeff:1@example.com"])
def test_register_rejects_reserved_email_hidden_by_format_characters(client, email):
    """Zero-width / BOM characters are Cf, not whitespace: strip() leaves them and
    the reserved check must still fire (a lookalike of a synthetic account)."""
    r = _register(client, email=email)
    assert r.status_code == 422
    assert "reserved" in r.get_json()["fields"]["email"]


def test_malformed_json_is_reported_as_malformed(client):
    r = client.post(f"{H}/users/register", data="{bad", content_type="application/json")
    assert r.status_code == 422
    assert r.get_json()["fields"] == {"body": "is not valid JSON"}
