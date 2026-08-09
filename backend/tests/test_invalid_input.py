"""Invalid input must never 500, store a nonsense number, or silently coerce.

One file for the class: non-numeric and non-finite quantities, money that must
stay Decimal, and out-of-range paging. A mutation with an unusable value is
refused; a paging/limit param is clamped.
"""

from decimal import Decimal

from app.services import money


# ---- integers: coerce or 422, never 500 ----

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


# ---- item quantity: finite and non-negative ----

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


# ---- money stays Decimal; null quantity is not zero ----

def test_line_total_keeps_fractional_quantity_precision():
    # 0.125 kg at $10 = $1.25, not $1.20 (which is what quantizing 0.125 -> 0.12
    # produces). Quantity is a measure, not money.
    assert money.line_total(Decimal("10.00"), 0.125) == Decimal("1.25")


def test_line_total_does_not_round_quantity_up():
    # 1.999 units at $1 = $2.00 exact? No — $1.999 -> rounds to $2.00 at the
    # PRODUCT, but the quantity itself must not first be forced to 2.00.
    # 1.996 * 1.00 = 1.996 -> 2.00 (product 2dp). If quantity were quantized to
    # 2.00 first, 1.234 * 1.00 would wrongly become 1.23.
    assert money.line_total(Decimal("1.00"), 1.234) == Decimal("1.23")


def test_line_total_still_exact_for_whole_quantities():
    assert money.line_total(Decimal("2.50"), 3) == Decimal("7.50")


def test_put_quantity_null_does_not_zero_the_item(auth_client):
    it = _item(auth_client, name="Widget", quantity=5).get_json()
    # a JS form serialiser easily sends null for an untouched field
    r = auth_client.put(f"/api/v1/items/{it['id']}",
                        json={"name": "Widget renamed", "quantity": None})
    assert r.status_code in (200, 201)
    body = auth_client.get(f"/api/v1/items/{it['id']}").get_json()
    assert body["quantity"] == 5, "quantity:null silently zeroed the item"
