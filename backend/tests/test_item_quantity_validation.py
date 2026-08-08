"""Item-form quantity must be validated like the holdings API.

The holdings API enforces quantity numeric-and-positive (_positive_qty), but the
item create/update/patch path wrote data["quantity"] raw onto item.quantity and
the single placement's holding. A negative stored a negative holding that
money.line_total multiplied into negative inventory valuations; a non-numeric
value reached resync_item's sum() and 500'd (and errored the Float column on
Postgres).
"""


def _item(c, **kw):
    return c.post("/api/v1/items", json=kw)


def test_negative_quantity_is_rejected_on_create(auth_client):
    r = _item(auth_client, name="Neg", quantity=-5)
    assert r.status_code == 422


def test_non_numeric_quantity_is_rejected_not_500(auth_client):
    r = _item(auth_client, name="Junk", quantity="abc")
    assert r.status_code == 422   # never a 500


def test_negative_quantity_is_rejected_on_update(auth_client):
    it = _item(auth_client, name="Ok", quantity=3).get_json()
    r = auth_client.put(f"/api/v1/items/{it['id']}", json={"quantity": -1})
    assert r.status_code == 422


def test_a_valid_quantity_still_works(auth_client):
    r = _item(auth_client, name="Fine", quantity=7)
    assert r.status_code in (200, 201)
    assert r.get_json()["quantity"] == 7


def _mk(c, **kw):
    return c.post("/api/v1/items", json={"name": "X", **kw})


def test_nan_quantity_is_rejected(auth_client):
    assert _mk(auth_client, quantity="nan").status_code == 422


def test_infinity_quantity_is_rejected(auth_client):
    r = _mk(auth_client, quantity="inf")
    assert r.status_code == 422, "Infinity passed → serialized as invalid JSON"


def test_nan_quantity_rejected_on_holdings_api(auth_client):
    it = _mk(auth_client, quantity=3).get_json()
    r = auth_client.post(f"/api/v1/items/{it['id']}/holdings", json={"quantity": "nan"})
    assert r.status_code == 422


def test_nan_quantity_rejected_on_update(auth_client):
    it = _mk(auth_client, quantity=3).get_json()
    assert auth_client.put(f"/api/v1/items/{it['id']}",
                           json={"quantity": "inf"}).status_code == 422
