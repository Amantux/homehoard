from datetime import datetime, timedelta

import pytest

from app.extensions import db
from app.models import Item
from app.services.alerts import alert_digest
from app.services.restock import restock_state


def _item(c, name, **kw):
    return c.post("/api/v1/items", json={"name": name, **kw}).get_json()


def test_summary_shape(auth_client):
    loc = auth_client.post("/api/v1/locations", json={"name": "Garage"}).get_json()
    auth_client.post("/api/v1/bins", json={"name": "Box", "locationId": loc["id"]})
    # An item with a warranty expiring in ~15 days.
    soon = (datetime.utcnow() + timedelta(days=15)).isoformat()
    item = auth_client.post("/api/v1/items", json={"name": "Router"}).get_json()
    auth_client.put(
        f"/api/v1/items/{item['id']}",
        json={"name": "Router", "warrantyExpires": soon, "insured": True,
              "purchasePrice": 100, "quantity": 1},
    )

    s = auth_client.get("/api/v1/ha/summary").get_json()
    assert s["health"] is True
    assert s["totals"]["items"] == 1
    assert s["totals"]["bins"] == 1
    assert s["totals"]["locations"] == 1
    assert s["totals"]["insuredValue"] == 100
    assert s["warrantiesExpiring"]["days30"] == 1
    assert s["warrantiesExpiring"]["items"][0]["name"] == "Router"


def test_summary_maintenance_overdue(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "Furnace"}).get_json()
    past = (datetime.utcnow() - timedelta(days=3)).isoformat()
    auth_client.post(
        f"/api/v1/items/{item['id']}/maintenance",
        json={"name": "Filter change", "scheduledDate": past},
    )
    s = auth_client.get("/api/v1/ha/summary").get_json()
    assert s["maintenance"]["overdue"] == 1
    assert s["maintenance"]["entries"][0]["overdue"] is True


def test_calendar_events(auth_client):
    item = auth_client.post("/api/v1/items", json={"name": "TV"}).get_json()
    exp = (datetime.utcnow() + timedelta(days=40)).isoformat()
    auth_client.put(
        f"/api/v1/items/{item['id']}",
        json={"name": "TV", "warrantyExpires": exp},
    )
    events = auth_client.get("/api/v1/ha/calendar").get_json()
    assert any(e["category"] == "warranty" and "TV" in e["summary"] for e in events)
    # each event has start/end for an all-day calendar entry
    assert all("start" in e and "end" in e for e in events)


def test_ha_requires_auth(client):
    assert client.get("/api/v1/ha/summary").status_code == 401


# --- what Home Assistant keeps ------------------------------------------------

def test_hidden_items_stay_out_of_every_list_ha_keeps_even_unlocked(auth_client, app):
    """These lists outlive any unlock: HA keeps them in sensor attributes and history,
    and the digest blueprint puts them on a phone. The integration's credential can be
    the unlocked one (the MCP server shares it), so a lock check is not enough."""
    soon = (datetime.utcnow() + timedelta(days=15)).isoformat()
    for name in ("AA batteries", "Secret Refill"):
        item = _item(auth_client, name, quantity=1, minQuantity=4, warrantyExpires=soon)
        assert auth_client.post(f"/api/v1/items/{item['id']}/checkout", json={}).status_code == 200
        auth_client.post(f"/api/v1/items/{item['id']}/maintenance",
                         json={"name": f"Service {name}", "scheduledDate": "2020-01-01"})
        if name == "Secret Refill":
            with app.app_context():
                db.session.get(Item, item["id"]).hidden = True
                db.session.commit()
    auth_client.post("/api/v1/vault/passphrase", json={"phrase": "open sesame"})
    assert auth_client.post(
        "/api/v1/vault/unlock", json={"phrase": "open sesame"}).status_code == 200
    # The unlock took: the app itself shows the hidden item to this credential.
    assert "Secret Refill" in auth_client.get("/api/v1/restock").get_data(as_text=True)

    r = auth_client.get("/api/v1/ha/summary")
    summary = r.get_json()

    assert "Secret Refill" not in r.get_data(as_text=True)
    for rows in (summary["restock"]["items"], summary["recentItems"],
                 summary["checkedOutItems"], summary["warrantiesExpiring"]["items"]):
        assert [x["name"] for x in rows] == ["AA batteries"]
    assert [x["name"] for x in summary["maintenance"]["entries"]] == ["Service AA batteries"]
    assert summary["restock"]["count"] == 1


@pytest.mark.parametrize("gone", [{"archived": True}, {"soldDate": "2026-01-01", "soldTo": "Bob"}])
def test_what_the_household_no_longer_keeps_is_not_reported(auth_client, app, gid, gone):
    """It used to nag every morning, with a live button, about things already gone."""
    item = _item(auth_client, "Old fridge", quantity=0, minQuantity=1)
    auth_client.post(f"/api/v1/items/{item['id']}/maintenance",
                     json={"name": "Descale", "scheduledDate": "2020-01-01"})
    summary = auth_client.get("/api/v1/ha/summary").get_json()
    assert summary["restock"]["count"] == 1 and summary["maintenance"]["overdue"] == 1

    assert auth_client.patch(f"/api/v1/items/{item['id']}", json=gone).status_code == 200

    summary = auth_client.get("/api/v1/ha/summary").get_json()
    assert summary["restock"] == {"count": 0, "items": []}
    assert summary["maintenance"]["overdue"] == 0 and summary["maintenance"]["entries"] == []
    assert auth_client.get("/api/v1/restock").get_json()["items"] == []
    assert auth_client.get("/api/v1/ha/calendar").get_json() == []
    with app.app_context():
        assert alert_digest(gid)["isEmpty"] is True
        assert restock_state(db.session.get(Item, item["id"]))["isLow"] is False


def test_summary_says_which_items_a_one_tap_restock_would_take(auth_client):
    """The digest offers "Bought" only where it would work: an item kept in several
    places has no single placement to add to, so that button would do nothing."""
    loc = auth_client.post("/api/v1/locations", json={"name": "Kitchen"}).get_json()
    one = _item(auth_client, "AA batteries", quantity=1, minQuantity=4)
    two = _item(auth_client, "Paint", quantity=1, minQuantity=4)
    auth_client.post(f"/api/v1/items/{two['id']}/holdings",
                     json={"locationId": loc["id"], "quantity": 1})

    rows = {r["id"]: r for r in
            auth_client.get("/api/v1/ha/summary").get_json()["restock"]["items"]}

    assert rows[one["id"]]["oneTap"] is True
    assert rows[two["id"]]["oneTap"] is False


def test_summary_carries_what_the_digest_blueprint_reads(auth_client):
    """The fields blueprints/automation/homehoard/ builds its message and buttons from."""
    item = _item(auth_client, "Furnace", quantity=1, minQuantity=4, targetQuantity=8)
    entry = auth_client.post(
        f"/api/v1/items/{item['id']}/maintenance",
        json={"name": "Filter change", "scheduledDate": "2020-01-01"},
    ).get_json()

    summary = auth_client.get("/api/v1/ha/summary").get_json()

    assert summary["restock"]["items"] == [{
        "id": item["id"], "name": "Furnace", "onHand": 1, "suggestedQuantity": 7,
        "oneTap": True,
    }]
    row = summary["maintenance"]["entries"][0]
    assert (row["id"], row["itemId"], row["name"], row["itemName"], row["overdue"]) == (
        entry["id"], item["id"], "Filter change", "Furnace", True)


# --- the one-tap contract -----------------------------------------------------
#
# Against the real POST /restock/<id>/restocked, because the integration's own tests
# have to mock it and so can't notice every Bought button being dead. That route
# ships in PR #71, so on a branch without it these fail with a 405. That is on
# purpose: the blueprint goes live by URL the moment it merges, so it must not land
# before the route does.

def _shown(c, item_id):
    """The digest's row for this item: what its notification would say."""
    rows = c.get("/api/v1/ha/summary").get_json()["restock"]["items"]
    return next((r for r in rows if r["id"] == item_id), None)


def _tap_bought(c, item_id, quantity):
    """What a Bought button sends."""
    return c.post(f"/api/v1/restock/{item_id}/restocked", json={"quantity": quantity})


def _on_hand(c, item_id):
    return c.get(f"/api/v1/items/{item_id}").get_json()["quantity"]


def test_one_tap_says_what_the_restock_route_will_do(auth_client):
    loc = auth_client.post("/api/v1/locations", json={"name": "Kitchen"}).get_json()
    one = _item(auth_client, "AA batteries", quantity=1, minQuantity=4, targetQuantity=8)
    two = _item(auth_client, "Paint", quantity=1, minQuantity=4, targetQuantity=8)
    auth_client.post(f"/api/v1/items/{two['id']}/holdings",
                     json={"locationId": loc["id"], "quantity": 1})

    row = _shown(auth_client, one["id"])
    assert row["oneTap"] is True
    assert _tap_bought(auth_client, one["id"], row["suggestedQuantity"]).status_code == 200

    row = _shown(auth_client, two["id"])
    assert row["oneTap"] is False
    assert _tap_bought(auth_client, two["id"], row["suggestedQuantity"]).status_code == 409


def test_a_tap_adds_the_number_the_notification_showed(auth_client):
    """Usage recorded after the digest went out changes today's suggestion, not what
    the person bought. Writing the suggestion at tap time took this count to 12."""
    item = _item(auth_client, "Cells", quantity=9, minQuantity=10, targetQuantity=12)
    shown = _shown(auth_client, item["id"])["suggestedQuantity"]
    assert shown == 3
    auth_client.patch(f"/api/v1/items/{item['id']}", json={"quantity": 0})

    r = _tap_bought(auth_client, item["id"], shown)

    assert r.status_code == 200
    assert r.get_json()["bought"] == 3 and r.get_json()["previousOnHand"] == 0
    assert _on_hand(auth_client, item["id"]) == 3


@pytest.mark.parametrize("policy", [
    {"minQuantity": 2},                             # no target
    {"minQuantity": 2, "targetQuantity": 2},        # target at the threshold
    {"minQuantity": 2, "targetQuantity": 8},        # a real target
])
def test_buying_what_the_digest_said_clears_the_item_and_a_second_phone_is_refused(
    auth_client, policy
):
    """The documented notify group gives a second phone the same live button: it must
    not add stock nobody bought, or leave someone being told to "buy 1" tomorrow."""
    item = _item(auth_client, "Bags", quantity=0, **policy)
    shown = _shown(auth_client, item["id"])["suggestedQuantity"]

    assert _tap_bought(auth_client, item["id"], shown).status_code == 200
    assert _shown(auth_client, item["id"]) is None
    on_hand = _on_hand(auth_client, item["id"])

    assert _tap_bought(auth_client, item["id"], shown).status_code == 422
    assert _on_hand(auth_client, item["id"]) == on_hand


@pytest.mark.parametrize("gone", [{"archived": True}, {"soldDate": "2026-01-01"}])
def test_a_tap_on_something_gone_since_the_digest_is_refused(auth_client, gone):
    item = _item(auth_client, "Mower oil", quantity=0, minQuantity=1)
    shown = _shown(auth_client, item["id"])["suggestedQuantity"]
    auth_client.patch(f"/api/v1/items/{item['id']}", json=gone)

    assert _tap_bought(auth_client, item["id"], shown).status_code == 422
    assert _on_hand(auth_client, item["id"]) == 0
