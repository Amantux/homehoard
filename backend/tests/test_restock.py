"""Low-stock / consumables: items with a min threshold surface a restock list.

Mirrors Edibl's reorder policy (the reference implementation per the SOP):
threshold = minQuantity; suggested = enough to reach targetQuantity (or the
threshold when no target); an item with NO minQuantity is never suggested —
most inventory (a drill, a couch) is not a consumable.
"""
from app.extensions import db
from app.models import Item


def _item(c, name, quantity=1, **kw):
    return c.post("/api/v1/items", json={"name": name, "quantity": quantity, **kw}).get_json()


def test_low_item_appears_with_a_suggested_quantity(auth_client):
    _item(auth_client, "AA batteries", quantity=2, minQuantity=4, targetQuantity=12)
    _item(auth_client, "Couch", quantity=1)   # no policy — never suggested

    r = auth_client.get("/api/v1/restock").get_json()

    assert [x["name"] for x in r["items"]] == ["AA batteries"]
    row = r["items"][0]
    assert row["onHand"] == 2 and row["threshold"] == 4
    assert row["suggestedQuantity"] == 10   # up to target


def test_item_at_threshold_counts_as_low_but_above_does_not(auth_client):
    _item(auth_client, "Tape", quantity=4, minQuantity=4)
    _item(auth_client, "Glue", quantity=5, minQuantity=4)

    names = [x["name"] for x in auth_client.get("/api/v1/restock").get_json()["items"]]

    assert "Tape" in names and "Glue" not in names


def test_no_target_suggests_reaching_the_threshold(auth_client):
    _item(auth_client, "Bags", quantity=1, minQuantity=6)

    row = auth_client.get("/api/v1/restock").get_json()["items"][0]

    assert row["suggestedQuantity"] == 5


def test_policy_fields_round_trip_on_the_item(auth_client):
    it = _item(auth_client, "Filters", quantity=3, minQuantity=2, targetQuantity=8)

    got = auth_client.get(f"/api/v1/items/{it['id']}").get_json()

    assert got["minQuantity"] == 2 and got["targetQuantity"] == 8
    auth_client.patch(f"/api/v1/items/{it['id']}", json={"minQuantity": None})
    got = auth_client.get(f"/api/v1/items/{it['id']}").get_json()
    assert got["minQuantity"] is None, "clearing the policy must stick"


def test_hidden_items_stay_out_of_the_restock_list_while_locked(auth_client, app):
    it = _item(auth_client, "Secret Consumable", quantity=0, minQuantity=2)
    with app.app_context():
        db.session.get(Item, it["id"]).hidden = True
        db.session.commit()

    names = [x["name"] for x in auth_client.get("/api/v1/restock").get_json()["items"]]

    assert "Secret Consumable" not in names


def test_restock_shows_up_in_the_ha_summary(auth_client):
    _item(auth_client, "AA batteries", quantity=1, minQuantity=4)

    summary = auth_client.get("/api/v1/ha/summary").get_json()

    assert summary["restock"]["count"] == 1
    assert summary["restock"]["items"][0]["name"] == "AA batteries"
