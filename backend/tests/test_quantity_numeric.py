"""Quantities are exact Numeric(12, 3) in the DB but JSON NUMBERS on the wire
(Flask would otherwise emit Decimal as a string)."""
import pytest


def _loc(c, name):
    return c.post("/api/v1/locations", json={"name": name}).get_json()


def _item(c, **kw):
    r = c.post("/api/v1/items", json=kw)
    return r.status_code, r.get_json()


def test_fractional_quantity_round_trips_as_a_json_float(auth_client):
    _, it = _item(auth_client, name="Flour", quantity=2.5)
    got = auth_client.get(f"/api/v1/items/{it['id']}").get_json()["quantity"]
    assert got == 2.5 and isinstance(got, float)


def test_whole_quantity_round_trips_as_a_json_int(auth_client):
    _, it = _item(auth_client, name="Cans", quantity=3)
    got = auth_client.get(f"/api/v1/items/{it['id']}").get_json()["quantity"]
    assert got == 3 and isinstance(got, int)


def test_point_one_plus_point_two_holdings_sum_to_exactly_point_three(auth_client):
    a, b = _loc(auth_client, "A"), _loc(auth_client, "B")
    _, it = _item(auth_client, name="Salt", quantity=0.1, locationId=a["id"])
    r = auth_client.post(f"/api/v1/items/{it['id']}/holdings",
                         json={"locationId": b["id"], "quantity": 0.2})
    assert r.status_code < 300
    got = auth_client.get(f"/api/v1/items/{it['id']}").get_json()["quantity"]
    assert got == 0.3  # float drift gives 0.30000000000000004


@pytest.mark.parametrize("bad", [1.2345, -1, "NaN", "Infinity", "abc", 1e12])
def test_unstorable_item_quantity_is_rejected(auth_client, bad):
    status, _ = _item(auth_client, name="Bad", quantity=bad)
    assert status == 422


def test_unstorable_holding_quantity_is_rejected(auth_client):
    a, b = _loc(auth_client, "A"), _loc(auth_client, "B")
    _, it = _item(auth_client, name="Rice", quantity=1, locationId=a["id"])
    r = auth_client.post(f"/api/v1/items/{it['id']}/holdings",
                         json={"locationId": b["id"], "quantity": 0.0001})
    assert r.status_code == 422
