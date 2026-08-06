"""Money is Decimal in the database and a float on the wire.

Two failure modes this guards, both silent:

* Flask renders a ``Decimal`` as a JSON **string** (``"19.99"``), which would
  change every price in the API from a number to a string and break arithmetic
  and formatting in the frontend.
* ``Decimal * float`` is a ``TypeError``, and ``Item.quantity`` is a float — so
  every ``price × quantity`` line total has to coerce.
"""
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Group, Item, MaintenanceEntry
from app.services import money


# --- the helper -------------------------------------------------------------

@pytest.mark.parametrize("given,expected", [
    (19.99, Decimal("19.99")),
    ("19.99", Decimal("19.99")),
    (Decimal("19.99"), Decimal("19.99")),
    (0.1, Decimal("0.10")),          # via str(): Decimal(0.1) would be 0.1000000000000000055…
    (None, Decimal("0.00")),
    ("", Decimal("0.00")),
    ("nonsense", Decimal("0.00")),   # a bad price must not 500 an otherwise-valid save
    ([1, 2], Decimal("0.00")),
    (float("nan"), Decimal("0.00")),   # Decimal("NaN").quantize() does NOT raise
    (float("inf"), Decimal("0.00")),
])
def test_to_money_coerces_without_raising(given, expected):
    assert money.to_money(given) == expected


def test_nan_never_reaches_the_wire():
    """A NaN would serialise as the bare token NaN — not valid JSON, so it
    breaks the client's parser instead of merely showing a wrong number."""
    import json

    assert money.to_money(float("nan")) == Decimal("0.00")
    assert json.dumps({"v": money.out(money.to_money(float("nan")))}) == '{"v": 0.0}'


def test_line_total_survives_a_float_quantity():
    """Item.quantity is a float column; Decimal * float raises TypeError."""
    assert money.line_total(Decimal("19.99"), 3.0) == Decimal("59.97")


def test_total_is_exact():
    assert money.total([(19.99, 3), (4.95, 7), (0.1, 3)]) == Decimal("94.92")


def test_out_produces_a_number_not_a_string():
    assert money.out(Decimal("19.99")) == 19.99
    assert isinstance(money.out(Decimal("19.99")), float)
    assert money.out(None) is None


# --- the wire contract ------------------------------------------------------

def _seed(app):
    with app.app_context():
        gid = db.session.query(Group).first().id
        item = Item(name="Drill", group_id=gid, purchase_price=Decimal("129.99"),
                    sold_price=Decimal("45.50"), quantity=3)
        db.session.add(item)
        db.session.flush()
        db.session.add(MaintenanceEntry(name="Service", item_id=item.id,
                                        cost=Decimal("19.99")))
        db.session.commit()
        return item.id


def test_prices_go_out_as_json_numbers(auth_client, app):
    """The regression that would break the frontend silently."""
    import json

    iid = _seed(app)
    raw = auth_client.get(f"/api/v1/items/{iid}").get_data(as_text=True)

    # Assert on the raw JSON text: "purchasePrice": 129.99, not "129.99".
    assert '"purchasePrice": 129.99' in raw or '"purchasePrice":129.99' in raw, raw[:400]
    body = json.loads(raw)
    assert isinstance(body["purchasePrice"], (int, float))
    assert not isinstance(body["purchasePrice"], str)


def test_statistics_totals_are_numbers_and_exact(auth_client, app):
    _seed(app)
    body = auth_client.get("/api/v1/groups/statistics").get_json()
    assert isinstance(body["totalItemPrice"], (int, float))
    assert body["totalItemPrice"] == pytest.approx(389.97)   # 129.99 x 3


def test_maintenance_cost_round_trips_through_the_api(auth_client, app):
    iid = _seed(app)
    r = auth_client.post(f"/api/v1/items/{iid}/maintenance",
                         json={"name": "Oil change", "cost": 12.345})
    assert r.status_code in (200, 201), r.get_json()
    # Quantized to 2dp on the way in, a number on the way out.
    assert r.get_json()["cost"] == 12.35 or r.get_json()["cost"] == 12.34


def test_a_junk_price_does_not_500_the_save(auth_client, app):
    iid = _seed(app)
    r = auth_client.put(f"/api/v1/items/{iid}", json={"purchasePrice": "not a number"})
    assert r.status_code == 200
    assert r.get_json()["purchasePrice"] == 0
