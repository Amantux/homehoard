"""Low-stock / consumables: items with a min threshold surface a restock list.

Mirrors Edibl's reorder policy (the reference implementation per the SOP):
threshold = minQuantity; suggested = enough to reach targetQuantity (or one past
the threshold when the target doesn't reach beyond it, since at the threshold
still counts as low); an item with NO minQuantity is never suggested — most
inventory (a drill, a couch) is not a consumable.
"""
import os
import threading
import uuid

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Item, User

PG_URL = os.environ.get("HBOX_TEST_PG_URL")


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


@pytest.mark.parametrize("target", [{}, {"targetQuantity": 6}, {"targetQuantity": 2}])
def test_with_no_target_above_the_threshold_it_suggests_one_past_it(auth_client, target):
    """Only reaching the threshold would leave the item low: buy 5, and it's still
    on the list, now asking for 1 more that nobody bought."""
    _item(auth_client, "Bags", quantity=1, minQuantity=6, **target)

    row = auth_client.get("/api/v1/restock").get_json()["items"][0]

    assert row["suggestedQuantity"] == 6


@pytest.mark.parametrize("on_hand, policy", [
    (1, {"minQuantity": 6}),                         # no target
    (1, {"minQuantity": 6, "targetQuantity": 6}),    # target at the threshold
    (1, {"minQuantity": 6, "targetQuantity": 2}),    # target below it
    (1.5, {"minQuantity": 2.5}),                     # fractional
    (0, {"minQuantity": 0}),                         # "low" means "out"
    (2, {"minQuantity": 4, "targetQuantity": 12}),   # a real target
    (3.75, {"minQuantity": 4, "targetQuantity": 4.5}),  # one barely above it
])
def test_buying_the_suggestion_takes_the_item_off_the_list(auth_client, on_hand, policy):
    it = _item(auth_client, "Bags", quantity=on_hand, **policy)

    body = _bought(auth_client, it["id"]).get_json()

    assert body["isLow"] is False
    assert auth_client.get("/api/v1/restock").get_json()["items"] == []


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


# ---- one-tap "Bought N" -----------------------------------------------------

def _bought(c, item_id, **kw):
    return c.post(f"/api/v1/restock/{item_id}/restocked", **kw)


def _quantities(c, item_id):
    """(the item's total, its per-placement quantities), as the API reports them."""
    got = c.get(f"/api/v1/items/{item_id}").get_json()
    return got["quantity"], [h["quantity"] for h in got["holdings"]]


def _second_placement(c, item_id, quantity=3):
    loc = c.post("/api/v1/locations", json={"name": "Garage"}).get_json()
    r = c.post(f"/api/v1/items/{item_id}/holdings",
               json={"locationId": loc["id"], "quantity": quantity})
    assert r.status_code == 201


def test_bought_adds_the_suggestion_to_on_hand(auth_client):
    it = _item(auth_client, "AA batteries", quantity=2, minQuantity=4, targetQuantity=12)

    r = _bought(auth_client, it["id"])

    assert r.status_code == 200
    body = r.get_json()
    assert body["onHand"] == 12          # 2 + the 10 it suggested, not "set to 10"
    assert body["bought"] == 10 and body["previousOnHand"] == 2
    assert body["isLow"] is False
    assert _quantities(auth_client, it["id"]) == (12, [12])
    assert auth_client.get("/api/v1/restock").get_json()["items"] == []


def test_bought_never_takes_stock_down(auth_client):
    """The suggestion is the amount to BUY: writing it as the new on-hand turned
    "8 on hand, buy 4" into 4 on hand."""
    it = _item(auth_client, "Filters", quantity=8, minQuantity=10, targetQuantity=12)

    assert _bought(auth_client, it["id"]).get_json()["onHand"] == 12
    assert _quantities(auth_client, it["id"]) == (12, [12])


def test_bought_quantity_is_how_many_were_bought(auth_client):
    it = _item(auth_client, "Paper towels", quantity=1, minQuantity=3, targetQuantity=10)

    body = _bought(auth_client, it["id"], json={"quantity": 5}).get_json()

    assert body["onHand"] == 6 and body["bought"] == 5
    assert body["suggestedQuantity"] == 4    # target 10 - on hand 6
    assert _quantities(auth_client, it["id"]) == (6, [6])


def test_bought_is_exact_on_fractional_quantities(auth_client):
    """Numeric(12, 3) columns: 0.1 + 0.2 is 0.3, and a fractional suggestion
    (a JSON float out of restock_state) must add to a Decimal without a 500."""
    it = _item(auth_client, "Rice", quantity=0.1, minQuantity=1, targetQuantity=2)

    assert _bought(auth_client, it["id"], json={"quantity": 0.2}).get_json()["onHand"] == 0.3

    body = _bought(auth_client, it["id"]).get_json()     # suggests 1.7
    assert body["bought"] == 1.7 and body["onHand"] == 2


@pytest.mark.parametrize("body", [None, {}, {"quantity": None}])
def test_bought_without_a_quantity_uses_the_suggestion(auth_client, body):
    it = _item(auth_client, "Bags", quantity=1, minQuantity=4, targetQuantity=6)

    r = _bought(auth_client, it["id"], json=body) if body is not None \
        else _bought(auth_client, it["id"])

    assert r.status_code == 200 and r.get_json()["onHand"] == 6


@pytest.mark.parametrize("bad", [0, -1, 1.1234, "abc", "", "NaN", "Infinity", True, 1e12])
def test_bought_refuses_a_quantity_that_is_not_a_purchase(auth_client, bad):
    it = _item(auth_client, "AA batteries", quantity=2, minQuantity=4)

    r = _bought(auth_client, it["id"], json={"quantity": bad})

    assert r.status_code == 422, bad
    assert "positive number" in r.get_json()["error"]
    assert _quantities(auth_client, it["id"]) == (2, [2])


def test_bought_refuses_a_total_the_column_cannot_hold(auth_client):
    it = _item(auth_client, "AA batteries", quantity=2, minQuantity=4)

    r = _bought(auth_client, it["id"], json={"quantity": 999999999.999})

    assert r.status_code == 422
    assert _quantities(auth_client, it["id"]) == (2, [2])


def test_bought_with_no_holding_counts_the_existing_stock_once(auth_client, app, gid):
    with app.app_context():
        legacy = Item(name="Legacy", quantity=3, min_quantity=4, target_quantity=10,
                      group_id=gid)
        db.session.add(legacy)
        db.session.commit()
        item_id = legacy.id
    assert _quantities(auth_client, item_id) == (3, [])

    body = _bought(auth_client, item_id).get_json()

    assert body["onHand"] == 10 and body["previousOnHand"] == 3
    assert _quantities(auth_client, item_id) == (10, [10])


@pytest.mark.parametrize("policy", [
    {"minQuantity": 8, "targetQuantity": 12},    # low (2 + 3 placed elsewhere)
    {"minQuantity": 1},                          # not low
    {},                                          # no policy at all
])
def test_several_placements_are_409_before_anything_else(auth_client, policy):
    """One tap never guesses which placement got the stock."""
    it = _item(auth_client, "AA batteries", quantity=2, **policy)
    _second_placement(auth_client, it["id"], quantity=3)

    r = _bought(auth_client, it["id"], json={"quantity": "junk"})

    assert r.status_code == 409
    assert "edit placements" in r.get_json()["error"]
    total, placed = _quantities(auth_client, it["id"])
    assert total == 5 and sorted(placed) == [2, 3]


def test_item_that_is_not_low_is_422(auth_client):
    it = _item(auth_client, "Tape", quantity=10, minQuantity=4)

    r = _bought(auth_client, it["id"])

    assert r.status_code == 422
    assert "no longer low" in r.get_json()["error"]
    assert _quantities(auth_client, it["id"]) == (10, [10])


def test_a_refused_tap_changes_nothing_not_even_the_change_cursor(auth_client):
    """The endpoint locks with a no-op UPDATE, which bumps updated_at. Committed, a
    refused tap would look like a change to every open view."""
    it = _item(auth_client, "Tape", quantity=10, minQuantity=4)
    before = auth_client.get("/api/v1/changes").get_json()["cursor"]

    assert _bought(auth_client, it["id"]).status_code == 422

    assert auth_client.get("/api/v1/changes").get_json()["cursor"] == before


def test_a_second_tab_tapping_the_same_suggestion_is_refused(auth_client):
    """Buying the suggestion clears the item, so the 422 above is what stops a tab
    that still shows the old row from counting the purchase twice."""
    it = _item(auth_client, "Bags", quantity=1, minQuantity=6)
    suggested = auth_client.get("/api/v1/restock").get_json()["items"][0]["suggestedQuantity"]

    assert _bought(auth_client, it["id"], json={"quantity": suggested}).status_code == 200
    assert _bought(auth_client, it["id"], json={"quantity": suggested}).status_code == 422

    assert _quantities(auth_client, it["id"]) == (7, [7])


def test_item_with_no_policy_is_422(auth_client):
    it = _item(auth_client, "Couch", quantity=1)

    r = _bought(auth_client, it["id"])

    assert r.status_code == 422
    assert "no longer has a Min quantity" in r.get_json()["error"]


def test_archived_item_is_treated_like_not_low(auth_client):
    """It is not on the list, so it cannot be tapped from it: a stale tab must not
    quietly move stock on something the household disposed of."""
    it = _item(auth_client, "Old filters", quantity=1, minQuantity=4)
    auth_client.patch(f"/api/v1/items/{it['id']}", json={"archived": True})

    r = _bought(auth_client, it["id"])

    assert r.status_code == 422
    assert _quantities(auth_client, it["id"]) == (1, [1])


def test_unknown_item_is_404(auth_client):
    assert _bought(auth_client, "no-such-item").status_code == 404


def test_another_households_item_is_404(auth_client, client):
    it = _item(auth_client, "Their batteries", quantity=1, minQuantity=4)
    mine = client.environ_base.pop("HTTP_AUTHORIZATION")
    client.post("/api/v1/users/register",
                json={"email": "o@o.com", "password": "password", "name": "O"})
    other = client.post("/api/v1/users/login",
                        json={"username": "o@o.com", "password": "password"}
                        ).get_json()["token"]

    r = client.post(f"/api/v1/restock/{it['id']}/restocked",
                    headers={"Authorization": other})

    assert r.status_code == 404
    client.environ_base["HTTP_AUTHORIZATION"] = mine
    assert _quantities(auth_client, it["id"]) == (1, [1])


def test_hidden_item_is_404_while_locked_and_works_once_unlocked(auth_client, app):
    it = _item(auth_client, "Secret Consumable", quantity=0, minQuantity=2)
    with app.app_context():
        db.session.get(Item, it["id"]).hidden = True
        db.session.commit()
    auth_client.post("/api/v1/vault/passphrase", json={"phrase": "open sesame"})

    assert _bought(auth_client, it["id"]).status_code == 404
    with app.app_context():
        assert db.session.get(Item, it["id"]).quantity == 0, "a refused tap wrote stock"

    # The same request succeeds once unlocked, so the 404 above was the vault.
    auth_client.post("/api/v1/vault/unlock", json={"phrase": "open sesame"})
    assert _bought(auth_client, it["id"]).get_json()["onHand"] == 3


def test_buying_too_little_leaves_the_row_low(auth_client):
    """What the Restock view's still-low toast is for. A tap sends the number on the
    button, so this happens when that number has gone out of date: someone used
    some since the list loaded."""
    it = _item(auth_client, "Bags", quantity=1, minQuantity=6)

    body = _bought(auth_client, it["id"], json={"quantity": 2}).get_json()

    assert body["onHand"] == 3 and body["isLow"] is True
    rows = auth_client.get("/api/v1/restock").get_json()["items"]
    assert [(r["id"], r["onHand"], r["suggestedQuantity"]) for r in rows] == [(it["id"], 3, 4)]


@pytest.mark.parametrize("start", [0, 2.5])
def test_undo_by_put_restores_a_single_holding(auth_client, start):
    """What the Restock view's Undo does. PUT accepts 0 (a holding's own PUT does
    not), so this works from empty too."""
    it = _item(auth_client, "Bags", quantity=start, minQuantity=6, targetQuantity=9)

    body = _bought(auth_client, it["id"]).get_json()
    assert body["onHand"] == 9

    r = auth_client.put(f"/api/v1/items/{it['id']}", json={"quantity": body["previousOnHand"]})

    assert r.status_code == 200 and r.get_json()["quantity"] == start
    assert _quantities(auth_client, it["id"]) == (start, [start])


def test_put_quantity_is_ignored_once_there_are_several_placements(auth_client):
    """Why the Restock view's Undo checks the count the server reports instead of
    trusting the 200: the holdings own the quantity, so this PUT changes nothing."""
    it = _item(auth_client, "Bags", quantity=1, minQuantity=6, targetQuantity=9)
    _bought(auth_client, it["id"])
    _second_placement(auth_client, it["id"], quantity=3)

    r = auth_client.put(f"/api/v1/items/{it['id']}", json={"quantity": 1})

    assert r.status_code == 200 and r.get_json()["quantity"] == 12


# ---- simultaneous taps: real threads, on each database ------------------------

@pytest.fixture(params=[
    "sqlite",
    pytest.param("postgres", marks=pytest.mark.skipif(
        not PG_URL, reason="set HBOX_TEST_PG_URL to a throwaway Postgres to run")),
])
def race_app(request, tmp_path):
    """An app on a fresh database, with a signed-in user's token. SQLite and Postgres
    serialize writers differently (with_for_update is a no-op on SQLite), so these
    tests prove the same code on both. CI's postgres-schema job runs that half."""
    url = f"sqlite:///{tmp_path}/race.db"
    if request.param == "postgres":
        server = make_url(PG_URL).set(drivername="postgresql")
        name = f"hh_restock_{uuid.uuid4().hex}"
        with psycopg.connect(server.render_as_string(hide_password=False),
                             autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        url = server.set(database=name).render_as_string(hide_password=False)

    class RaceConfig(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = url
        DISABLE_AUTH = False
        SECRET_KEY = "test-secret-key-that-is-long-enough-32b"
        RATELIMIT_ENABLED = False
        PROXY_HOPS = 0
        WORKER_ENABLED = False

    app = create_app(RaceConfig)
    c = app.test_client()
    c.post("/api/v1/users/register",
           json={"email": "t@t.com", "password": "password", "name": "T"})
    token = c.post("/api/v1/users/login", json={"username": "t@t.com", "password": "password"}
                   ).get_json()["token"]
    # Fill the connection pool first. Otherwise the thread that gets the one open
    # connection finishes while the others are still connecting, and nothing overlaps.
    _at_once(app, token, "warm-up", 8, {})
    yield app, token
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _at_once(app, token, item_id, n, body):
    """POST the same purchase from n threads released together; the responses."""
    barrier = threading.Barrier(n)
    responses = []

    def tap():
        c = app.test_client()
        barrier.wait()
        responses.append(c.post(f"/api/v1/restock/{item_id}/restocked", json=body,
                                headers={"Authorization": token}))

    threads = [threading.Thread(target=tap) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return responses


def _new_item(app, token, **kw):
    r = app.test_client().post("/api/v1/items", json=kw, headers={"Authorization": token})
    assert r.status_code == 201
    return r.get_json()["id"]


def _stock(app, token, item_id):
    got = app.test_client().get(f"/api/v1/items/{item_id}",
                                headers={"Authorization": token}).get_json()
    return got["quantity"], [h["quantity"] for h in got["holdings"]]


def test_simultaneous_purchases_are_all_counted(race_app):
    """Writing "the count I read + N" lost all but a few of these behind 200s."""
    app, token = race_app
    item_id = _new_item(app, token, name="Bags", quantity=1, minQuantity=1000)

    responses = _at_once(app, token, item_id, 12, {"quantity": 1})

    assert [r.status_code for r in responses] == [200] * 12
    assert _stock(app, token, item_id) == (13, [13])
    # Each was judged on what the one before it left, which is what Undo relies on.
    assert sorted(r.get_json()["previousOnHand"] for r in responses) == list(range(1, 13))


def test_simultaneous_taps_on_one_suggestion_count_once(race_app):
    """The first clears the item. The rest see that and are refused, as they would be
    one after another, rather than each adding to a count nobody re-read."""
    app, token = race_app
    item_id = _new_item(app, token, name="Filters", quantity=8, minQuantity=10, targetQuantity=12)

    responses = _at_once(app, token, item_id, 8, {"quantity": 4})

    assert sorted(r.status_code for r in responses) == [200] + [422] * 7
    assert _stock(app, token, item_id) == (12, [12])


def test_simultaneous_purchases_with_no_holding_make_exactly_one(race_app):
    """Each used to see "no holding yet" and create one: two placements, and a stored
    total that disagreed with their sum."""
    app, token = race_app
    with app.app_context():
        gid = db.session.query(User).filter_by(email="t@t.com").first().group_id
        legacy = Item(name="Legacy", quantity=3, min_quantity=1000, group_id=gid)
        db.session.add(legacy)
        db.session.commit()
        item_id = legacy.id

    responses = _at_once(app, token, item_id, 6, {"quantity": 1})

    assert [r.status_code for r in responses] == [200] * 6
    assert _stock(app, token, item_id) == (9, [9])
