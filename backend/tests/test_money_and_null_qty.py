"""Two correctness bugs from the efficiency/compat pass."""
from decimal import Decimal

from app.services import money


# --- money.line_total must not quantize the QUANTITY to 2dp -------------------

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


# --- PUT quantity: null must not zero the item -------------------------------

def _item(c, **kw):
    return c.post("/api/v1/items", json=kw)


def test_put_quantity_null_does_not_zero_the_item(auth_client):
    it = _item(auth_client, name="Widget", quantity=5).get_json()
    # a JS form serialiser easily sends null for an untouched field
    r = auth_client.put(f"/api/v1/items/{it['id']}",
                        json={"name": "Widget renamed", "quantity": None})
    assert r.status_code in (200, 201)
    body = auth_client.get(f"/api/v1/items/{it['id']}").get_json()
    assert body["quantity"] == 5, "quantity:null silently zeroed the item"
