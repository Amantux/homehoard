"""GET /api/v1/changes?since=<ISO8601> — the per-visit "what changed" delta.

The Dashboard's since-visit strip asks the backend what happened since the
user's last visit and renders it. The four counters are computed server-side
against the caller's current group and reuse the /ha/summary policies (warranty
dates by calendar date against the household's local today, vault-visible items).
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Item
from app.timeutil import to_local, utcnow

FAR_PAST = "2000-01-01T00:00:00Z"
FAR_FUTURE = "2999-01-01T00:00:00Z"


def _digest(auth_client, since):
    res = auth_client.get(f"/api/v1/changes?since={since}")
    assert res.status_code == 200, (res.status_code, res.get_data(as_text=True))
    return res.get_json()


def _item(auth_client, name, **kw):
    return auth_client.post("/api/v1/items", json={"name": name, **kw}).get_json()


def test_digest_empty_when_since_is_in_the_future(auth_client):
    """Nothing changed since a point nothing could have happened after -> zeros."""
    body = _digest(auth_client, FAR_FUTURE)
    assert body["since"] == "2999-01-01T00:00:00+00:00"
    assert set(body) == {
        "since", "newItems", "checkoutsReturned", "warrantiesExpiring7", "maintenanceCompleted",
    }
    assert body["newItems"] == 0
    assert body["checkoutsReturned"] == 0
    assert body["warrantiesExpiring7"] == 0
    assert body["maintenanceCompleted"] == 0


def test_digest_counts_only_what_happened_since(auth_client, app):
    """The since cutoff is honoured: an item created before `since` is not new."""
    item = _item(auth_client, "Drill")
    with app.app_context():
        db.session.get(Item, item["id"]).created_at = datetime(2020, 1, 1)
        db.session.commit()

    assert _digest(auth_client, FAR_PAST)["newItems"] == 1
    assert _digest(auth_client, "2021-01-01T00:00:00Z")["newItems"] == 0


def test_digest_checkouts_returned_counts_checkins_since(auth_client):
    """A check-in is a CheckoutEntry with action="in"; its created_at is the return."""
    item = _item(auth_client, "Drill")
    auth_client.post(f"/api/v1/items/{item['id']}/checkout", json={"person": "Sam"})
    back = auth_client.post(f"/api/v1/items/{item['id']}/checkin", json={})
    assert back.status_code == 200

    assert _digest(auth_client, FAR_PAST)["checkoutsReturned"] == 1
    assert _digest(auth_client, FAR_FUTURE)["checkoutsReturned"] == 0


def test_digest_warranties_expiring_7_window(auth_client, app):
    """Expiring-7 is [local today, local today + 7] over active warranties."""
    today = to_local(utcnow()).date()
    _item(auth_client, "Soon", warrantyExpires=(today + timedelta(days=3)).isoformat())
    _item(auth_client, "Edge", warrantyExpires=(today + timedelta(days=7)).isoformat())
    _item(auth_client, "Later", warrantyExpires=(today + timedelta(days=9)).isoformat())
    _item(auth_client, "Expired", warrantyExpires=(today - timedelta(days=5)).isoformat())
    _item(auth_client, "Forever", lifetimeWarranty=True)

    assert _digest(auth_client, FAR_PAST)["warrantiesExpiring7"] == 2


def test_digest_maintenance_completed_since(auth_client):
    """A completed maintenance entry is counted once completedDate passes `since`."""
    item = _item(auth_client, "Furnace")
    made = auth_client.post(
        f"/api/v1/items/{item['id']}/maintenance",
        json={"name": "Filter change", "scheduledDate": "2026-01-15"},
    ).get_json()
    done = auth_client.put(
        f"/api/v1/items/{item['id']}/maintenance/{made['id']}",
        json={"completedDate": "2026-01-20"},
    )
    assert done.status_code == 200

    assert _digest(auth_client, FAR_PAST)["maintenanceCompleted"] == 1
    assert _digest(auth_client, FAR_FUTURE)["maintenanceCompleted"] == 0


def test_digest_rejects_unparseable_since(auth_client):
    res = auth_client.get("/api/v1/changes?since=not-a-timestamp")
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_digest_rejects_empty_since(auth_client):
    res = auth_client.get("/api/v1/changes?since=")
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_digest_bare_changes_is_the_cursor_not_a_delta(auth_client):
    """No `since` key at all -> the bare live-sync cursor, never a delta: a first
    visit has no stored watermark yet, and the SPA seeds its first one at the
    epoch before asking for a delta. The delta shape is entered by naming
    `since`, so a missing value never silently means "everything" or "nothing".
    """
    res = auth_client.get("/api/v1/changes")
    assert res.status_code == 200
    assert set(res.get_json()) == {"cursor"}


def test_digest_first_visit_seeds_its_watermark_at_the_epoch(auth_client):
    """First visit: the client seeds its stored watermark at the epoch, so the
    first real delta reports everything created since then as new."""
    _item(auth_client, "Drill")
    _item(auth_client, "Saw")
    assert _digest(auth_client, FAR_PAST)["newItems"] == 2


def test_digest_requires_auth(client):
    res = client.get(f"/api/v1/changes?since={FAR_PAST}")
    assert res.status_code == 401


def test_digest_is_scoped_to_the_callers_group(client, auth_client, app):
    """No other household's rows leak into this group's delta."""
    today = to_local(utcnow()).date()
    mine = _item(auth_client, "Mine")
    other = client.post(
        "/api/v1/users/register",
        json={"email": "other@easyinventory.com", "password": "pw123456", "name": "O",
              "groupName": "Other"},
    )
    other_token = client.post(
        "/api/v1/users/login",
        json={"username": "other@easyinventory.com", "password": "pw123456"},
    ).get_json()["token"]
    saved = client.environ_base.get("HTTP_AUTHORIZATION")
    client.environ_base["HTTP_AUTHORIZATION"] = other_token
    theirs = client.post(
        "/api/v1/items",
        json={"name": "Theirs", "warrantyExpires": (today + timedelta(days=2)).isoformat()},
    ).get_json()
    client.environ_base["HTTP_AUTHORIZATION"] = saved

    assert theirs["id"] != mine["id"]
    body = _digest(auth_client, FAR_PAST)
    assert body["newItems"] == 1
    assert body["checkoutsReturned"] == 0
    assert body["maintenanceCompleted"] == 0
    # The other household's soon-expiring warranty is not this group's delta.
    assert body["warrantiesExpiring7"] == 0

    client.environ_base["HTTP_AUTHORIZATION"] = other_token
    theirs_body = client.get(f"/api/v1/changes?since={FAR_PAST}").get_json()
    client.environ_base["HTTP_AUTHORIZATION"] = saved
    assert theirs_body["newItems"] == 1
    assert theirs_body["warrantiesExpiring7"] == 1


def test_digest_excludes_hidden_items(auth_client, app):
    """Counts follow the vault-visible policy: hidden items are not new."""
    item = _item(auth_client, "Secret")
    with app.app_context():
        db.session.get(Item, item["id"]).hidden = True
        db.session.commit()

    assert _digest(auth_client, FAR_PAST)["newItems"] == 0
