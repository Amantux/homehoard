"""Maintenance recurrence: completing an entry with recur_months rolls it
forward — one new scheduled entry at completed_date + N calendar months, the
completed entry kept as history. One-shot entries (recur_months NULL) are
untouched."""


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
