"""Low-stock / consumables: items with a min threshold surface a restock list.

Mirrors Edibl's reorder policy (the reference implementation per the SOP):
threshold = minQuantity; suggested = enough to reach targetQuantity (or the
threshold when no target); an item with NO minQuantity is never suggested —
most inventory (a drill, a couch) is not a consumable.
"""
from app.extensions import db
from app.models import Item


def _loc(c, name):
    return c.post("/api/v1/locations", json={"name": name}).get_json()


def _bin(c, name, loc_id):
    return c.post("/api/v1/bins", json={"name": name, "locationId": loc_id}).get_json()


def _item(c, **kw):
    return c.post("/api/v1/items", json=kw).get_json()


def test_low_item_appears_with_a_suggested_quantity(auth_client):
    _item(auth_client, name="AA batteries", quantity=2, minQuantity=4, targetQuantity=12)
    _item(auth_client, name="Couch", quantity=1)   # no policy — never suggested

    r = auth_client.get("/api/v1/restock").get_json()

    assert [x["name"] for x in r["items"]] == ["AA batteries"]
    row = r["items"][0]
    assert row["onHand"] == 2 and row["threshold"] == 4
    assert row["suggestedQuantity"] == 10   # up to target


def test_item_at_threshold_counts_as_low_but_above_does_not(auth_client):
    _item(auth_client, name="Tape", quantity=4, minQuantity=4)
    _item(auth_client, name="Glue", quantity=5, minQuantity=4)

    names = [x["name"] for x in auth_client.get("/api/v1/restock").get_json()["items"]]

    assert "Tape" in names and "Glue" not in names


def test_no_target_suggests_reaching_the_threshold(auth_client):
    _item(auth_client, name="Bags", quantity=1, minQuantity=6)

    row = auth_client.get("/api/v1/restock").get_json()["items"][0]

    assert row["suggestedQuantity"] == 5


def test_policy_fields_round_trip_on_the_item(auth_client):
    it = _item(auth_client, name="Filters", quantity=3, minQuantity=2, targetQuantity=8)

    got = auth_client.get(f"/api/v1/items/{it['id']}").get_json()

    assert got["minQuantity"] == 2 and got["targetQuantity"] == 8
    auth_client.patch(f"/api/v1/items/{it['id']}", json={"minQuantity": None})
    got = auth_client.get(f"/api/v1/items/{it['id']}").get_json()
    assert got["minQuantity"] is None, "clearing the policy must stick"


def test_hidden_items_stay_out_of_the_restock_list_while_locked(auth_client, app):
    it = _item(auth_client, name="Secret Consumable", quantity=0, minQuantity=2)
    with app.app_context():
        db.session.get(Item, it["id"]).hidden = True
        db.session.commit()

    names = [x["name"] for x in auth_client.get("/api/v1/restock").get_json()["items"]]

    assert "Secret Consumable" not in names


def test_restock_shows_up_in_the_ha_summary(auth_client):
    _item(auth_client, name="AA batteries", quantity=1, minQuantity=4)

    summary = auth_client.get("api/v1/ha/summary").get_json()

    assert summary["restock"]["count"] == 1
    assert summary["restock"]["items"][0]["name"] == "AA batteries"


def test_restocked_marks_single_holding_item_as_restocked(auth_client):
    it = _item(auth_client, name="AA batteries", quantity=2, minQuantity=4, targetQuantity=12)
    # Before restock
    r = auth_client.get(f"/api/v1/items/{it['id']}").get_json()
    assert r["quantity"] == 2

    # Restock without body (uses suggestedQuantity)
    restocked_resp = auth_client.post(f"/api/v1/restock/{it['id']}/restocked")
    restocked = restocked_resp.get_json()
    assert restocked["onHand"] == 10  # targetQuantity (12) - onHand (2) = 10 needed
    assert restocked["suggestedQuantity"] == 2

    # Verify item quantity was updated
    r = auth_client.get(f"/api/v1/items/{it['id']}").get_json()
    assert r["quantity"] == 10


def test_restocked_with_override_quantity(auth_client):
    it = _item(auth_client, name="Paper towels", quantity=1, minQuantity=3, targetQuantity=10)

    # Override with custom quantity
    restocked = auth_client.post(
        f"/api/v1/restock/{it['id']}/restocked",
        json={"quantity": 5}
    ).get_json()

    assert restocked["onHand"] == 5
    assert restocked["suggestedQuantity"] == 5  # target 10 - onHand 5

    r = auth_client.get(f"/api/v1/items/{it['id']}").get_json()
    assert r["quantity"] == 5


def test_restocked_item_not_low_returns_422(auth_client):
    it = _item(auth_client, name="Tape", quantity=10, minQuantity=4)  # Not low

    r = auth_client.post(f"/api/v1/restock/{it['id']}/restocked")
    assert r.status_code == 422
    assert "not low" in r.get_json()["error"].lower()


def test_restocked_no_policy_returns_422(auth_client):
    it = _item(auth_client, name="Couch", quantity=1)  # No minQuantity

    r = auth_client.post(f"/api/v1/restock/{it['id']}/restocked")
    assert r.status_code == 422
    assert "no restock policy" in r.get_json()["error"].lower()


def test_restocked_multi_holding_returns_409(auth_client):
    loc = _loc(auth_client, "Kitchen")
    b1, b2 = _bin(auth_client, "Drawer", loc["id"]), _bin(auth_client, "Garage", loc["id"])
    it = _item(auth_client, name="AA batteries", quantity=2, minQuantity=4, targetQuantity=12, binId=b1["id"])

    # Add a second placement
    auth_client.post(f"/api/v1/items/{it['id']}/holdings",
                     json={"binId": b2["id"], "quantity": 3})

    r = auth_client.post(f"/api/v1/restock/{it['id']}/restocked")
    assert r.status_code == 409
    assert "edit placements" in r.get_json()["error"].lower()


def test_restocked_item_not_found_returns_404(auth_client):
    r = auth_client.post("/api/v1/restock/999999/restocked")
    assert r.status_code == 404


def test_restocked_item_hidden_returns_404(auth_client, app):
    it = _item(auth_client, name="Secret Consumable", quantity=0, minQuantity=2)
    with app.app_context():
        item = db.session.get(Item, it["id"])
        if item:
            item.hidden = True
            db.session.commit()

    r = auth_client.post(f"/api/v1/restock/{it['id']}/restocked")
    assert r.status_code == 404


def test_restocked_invalid_quantity_returns_422(auth_client):
    it = _item(auth_client, name="AA batteries", quantity=2, minQuantity=4)

    # Negative quantity
    r = auth_client.post(f"/api/v1/restock/{it['id']}/restocked",
                         json={"quantity": -1})
    assert r.status_code == 422

    # Too many decimal places
    r = auth_client.post(f"/api/v1/restock/{it['id']}/restocked",
                         json={"quantity": 1.1234})
    assert r.status_code == 422
