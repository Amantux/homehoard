"""Maintenance recurrence: completing an entry with recur_months rolls it
forward — one new scheduled entry at completed_date + N calendar months, the
completed entry kept as history. One-shot entries (recur_months NULL) are
untouched."""
import pytest

from app.extensions import db
from app.models import Item


def _make_item(auth_client, name="Furnace"):
    return auth_client.post("/api/v1/items", json={"name": name}).get_json()


def _entries(auth_client, item_id):
    return auth_client.get(
        f"/api/v1/items/{item_id}/maintenance"
    ).get_json()["entries"]


def test_recur_months_round_trips_on_create_and_update(auth_client):
    item = _make_item(auth_client)

    made = auth_client.post(
        f"/api/v1/items/{item['id']}/maintenance",
        json={"name": "Filter change", "recurMonths": 6,
              "scheduledDate": "2026-01-15"},
    ).get_json()
    assert made["recurMonths"] == 6

    updated = auth_client.put(
        f"/api/v1/items/{item['id']}/maintenance/{made['id']}",
        json={"recurMonths": 3},
    ).get_json()
    assert updated["recurMonths"] == 3

    cleared = auth_client.put(
        f"/api/v1/items/{item['id']}/maintenance/{made['id']}",
        json={"recurMonths": None},
    ).get_json()
    assert cleared["recurMonths"] is None


def test_completing_recurring_entry_spawns_next_scheduled_entry(auth_client):
    item = _make_item(auth_client)
    made = auth_client.post(
        f"/api/v1/items/{item['id']}/maintenance",
        json={"name": "Filter change", "description": "MERV 13",
              "recurMonths": 6, "scheduledDate": "2026-01-15"},
    ).get_json()

    auth_client.put(
        f"/api/v1/items/{item['id']}/maintenance/{made['id']}",
        json={"completedDate": "2026-01-20"},
    )

    entries = _entries(auth_client, item["id"])
    assert len(entries) == 2
    nxt = next(e for e in entries if e["id"] != made["id"])
    assert nxt["name"] == "Filter change"
    assert nxt["description"] == "MERV 13"
    assert nxt["recurMonths"] == 6
    assert nxt["completedDate"] is None
    assert nxt["scheduledDate"].startswith("2026-07-20")
    # history entry is kept, still completed
    prev = next(e for e in entries if e["id"] == made["id"])
    assert prev["completedDate"] is not None


def test_completing_twice_spawns_exactly_once(auth_client):
    item = _make_item(auth_client)
    made = auth_client.post(
        f"/api/v1/items/{item['id']}/maintenance",
        json={"name": "Filter change", "recurMonths": 6},
    ).get_json()

    for _ in range(2):  # second PUT re-sends the same completedDate
        auth_client.put(
            f"/api/v1/items/{item['id']}/maintenance/{made['id']}",
            json={"completedDate": "2026-01-20"},
        )

    assert len(_entries(auth_client, item["id"])) == 2


def test_month_end_clamps_jan_31_plus_one_month(auth_client):
    item = _make_item(auth_client)
    made = auth_client.post(
        f"/api/v1/items/{item['id']}/maintenance",
        json={"name": "Descale", "recurMonths": 1},
    ).get_json()

    auth_client.put(
        f"/api/v1/items/{item['id']}/maintenance/{made['id']}",
        json={"completedDate": "2026-01-31"},
    )

    entries = _entries(auth_client, item["id"])
    nxt = next(e for e in entries if e["id"] != made["id"])
    # 2026 is not a leap year: Jan 31 + 1 month clamps to Feb 28.
    assert nxt["scheduledDate"].startswith("2026-02-28")


def test_one_shot_entry_completion_spawns_nothing(auth_client):
    item = _make_item(auth_client)
    made = auth_client.post(
        f"/api/v1/items/{item['id']}/maintenance",
        json={"name": "Repair hinge"},
    ).get_json()
    assert made["recurMonths"] is None

    auth_client.put(
        f"/api/v1/items/{item['id']}/maintenance/{made['id']}",
        json={"completedDate": "2026-01-20"},
    )

    assert len(_entries(auth_client, item["id"])) == 1


def test_creating_already_completed_recurring_entry_spawns_next(auth_client):
    # Logging "done today, repeat every 6 months" in one step must also roll
    # forward — the create path accepts completedDate.
    item = _make_item(auth_client)
    auth_client.post(
        f"/api/v1/items/{item['id']}/maintenance",
        json={"name": "Filter change", "recurMonths": 6,
              "completedDate": "2026-01-20"},
    )

    entries = _entries(auth_client, item["id"])
    assert len(entries) == 2
    assert any(e["scheduledDate"] and e["scheduledDate"].startswith("2026-07-20")
               for e in entries)


def test_recur_months_rejects_garbage_as_one_shot(auth_client):
    item = _make_item(auth_client)
    made = auth_client.post(
        f"/api/v1/items/{item['id']}/maintenance",
        json={"name": "X", "recurMonths": "soon"},
    ).get_json()
    assert made["recurMonths"] is None

    zero = auth_client.post(
        f"/api/v1/items/{item['id']}/maintenance",
        json={"name": "Y", "recurMonths": 0},
    ).get_json()
    assert zero["recurMonths"] is None


# --- onlyIfOpen: what a notification's "Done" sends ---------------------------

def _overdue_recurring(auth_client, item):
    return auth_client.post(
        f"/api/v1/items/{item['id']}/maintenance",
        json={"name": "Filter change", "recurMonths": 6, "scheduledDate": "2020-01-01"},
    ).get_json()


def _done(auth_client, item, entry, day="2026-11-06"):
    return auth_client.put(
        f"/api/v1/items/{item['id']}/maintenance/{entry['id']}",
        json={"completedDate": day, "onlyIfOpen": True},
    )


def test_done_on_an_open_entry_completes_it_and_rolls_forward(auth_client):
    item = _make_item(auth_client)
    entry = _overdue_recurring(auth_client, item)

    r = _done(auth_client, item, entry)

    assert r.status_code == 200
    assert r.get_json()["completedDate"].startswith("2026-11-06")
    assert [e["scheduledDate"][:10] for e in _entries(auth_client, item["id"])
            if not e["completedDate"]] == ["2027-05-06"]


def test_a_stale_done_cannot_rewrite_when_the_job_was_done(auth_client):
    """An old notification, or the other phone in a notify group. It used to answer
    200 and move the completed date, with the next occurrence left where it was."""
    item = _make_item(auth_client)
    entry = _overdue_recurring(auth_client, item)
    assert _done(auth_client, item, entry, "2026-01-01").status_code == 200
    before = _entries(auth_client, item["id"])

    r = _done(auth_client, item, entry)

    assert r.status_code == 409
    assert _entries(auth_client, item["id"]) == before


@pytest.mark.parametrize("gone", [{"archived": True}, {"soldDate": "2026-01-01"}])
def test_done_on_what_the_household_no_longer_keeps_is_refused(auth_client, gone):
    """It would otherwise schedule the next occurrence on something that's gone."""
    item = _make_item(auth_client)
    entry = _overdue_recurring(auth_client, item)
    assert auth_client.patch(f"/api/v1/items/{item['id']}", json=gone).status_code == 200

    assert _done(auth_client, item, entry).status_code == 409
    assert [e["completedDate"] for e in _entries(auth_client, item["id"])] == [None]


def test_done_on_a_hidden_items_entry_is_404_while_locked(auth_client, app):
    """Checked before the 409: "this exists but is no longer open" would be the leak."""
    item = _make_item(auth_client)
    entry = _overdue_recurring(auth_client, item)
    assert _done(auth_client, item, entry, "2026-01-01").status_code == 200
    with app.app_context():
        db.session.get(Item, item["id"]).hidden = True
        db.session.commit()

    assert _done(auth_client, item, entry).status_code == 404


def test_the_apps_own_edit_can_still_correct_a_completed_date(auth_client):
    """No onlyIfOpen, no refusal: fixing a date in the app is a real edit."""
    item = _make_item(auth_client)
    entry = _overdue_recurring(auth_client, item)
    assert _done(auth_client, item, entry, "2026-01-01").status_code == 200

    r = auth_client.put(
        f"/api/v1/items/{item['id']}/maintenance/{entry['id']}",
        json={"completedDate": "2026-01-02"},
    )

    assert r.status_code == 200
    assert r.get_json()["completedDate"].startswith("2026-01-02")
