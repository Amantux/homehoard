"""Notifiers used to be CRUD-only — nothing ever sent. POST /notifiers/dispatch
builds the current alert digest and sends it to the group's active notifiers
(meant to be driven by an HA automation, since the add-on has no scheduler).
Every URL is re-validated at send time (SSRF), and the digest logic is shared
with the HA summary sensor.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.extensions import db
from app.models import Group, Item, MaintenanceEntry, Notifier
from app.services.alerts import alert_digest
from app.services.notify import send_to_notifiers, url_is_safe


# ---- digest (shared policy) ------------------------------------------------

def test_alert_digest_collects_the_three_alert_kinds(auth_client, app):
    now = datetime(2026, 8, 8, 12, 0, 0)
    with app.app_context():
        gid = db.session.query(Group).first().id
        db.session.add(Item(name="Ladder", group_id=gid, checked_out=True,
                            checked_out_to="Bob",
                            checkout_due=now - timedelta(days=2)))
        db.session.add(Item(name="Laptop", group_id=gid,
                            warranty_expires=now + timedelta(days=10)))
        drill = Item(name="Drill", group_id=gid)
        db.session.add(drill)
        db.session.flush()
        db.session.add(MaintenanceEntry(name="Oil change", item_id=drill.id,
                                        scheduled_date=now - timedelta(days=5)))
        db.session.commit()
        digest = alert_digest(gid, now=now)
    assert digest["counts"] == {"overdueCheckouts": 1,
                                "warrantyExpiringSoon": 1,
                                "maintenanceOverdue": 1}
    assert digest["isEmpty"] is False
    assert "Ladder" in digest["text"] and "Oil change" in digest["text"]


def test_alert_digest_is_empty_with_nothing_due(auth_client, app):
    with app.app_context():
        gid = db.session.query(Group).first().id
        db.session.add(Item(name="Mug", group_id=gid))  # no warranty/checkout
        db.session.commit()
        digest = alert_digest(gid)
    assert digest["isEmpty"] is True and digest["counts"]["overdueCheckouts"] == 0


# ---- SSRF guard at send time (mutation-checkable) --------------------------

def test_send_refuses_internal_urls_and_never_calls_the_sender():
    calls = []
    notifiers = [SimpleNamespace(id="a", url="http://169.254.169.254/latest"),
                 SimpleNamespace(id="b", url="tgram://token/123456")]
    results = send_to_notifiers(notifiers, title="t", body="b",
                                sender=lambda u, t, bd: calls.append(u) or True)
    by_id = {r["id"]: r for r in results}
    assert by_id["a"]["ok"] is False and by_id["a"]["error"] == "blocked"
    assert by_id["b"]["ok"] is True
    # the blocked URL was never handed to the sender
    assert "http://169.254.169.254/latest" not in calls
    assert calls == ["tgram://token/123456"]


def test_url_is_safe_blocks_metadata_allows_provider_scheme():
    assert url_is_safe("http://169.254.169.254/") is False
    assert url_is_safe("http://127.0.0.1:8080/hook") is False
    assert url_is_safe("tgram://bottoken/chatid") is True


# ---- endpoint --------------------------------------------------------------

def _add_notifier(app, gid, user_id, url="tgram://tok/chat"):
    with app.app_context():
        n = Notifier(name="phone", url=url, is_active=True,
                     group_id=gid, user_id=user_id)
        db.session.add(n)
        db.session.commit()


def _ids(app):
    with app.app_context():
        g = db.session.query(Group).first()
        from app.models import User
        u = db.session.query(User).first()
        return g.id, u.id


def test_dispatch_skips_when_no_alerts(auth_client, app):
    gid, uid = _ids(app)
    _add_notifier(app, gid, uid)
    r = auth_client.post("/api/v1/notifiers/dispatch")
    assert r.status_code == 200
    body = r.get_json()
    assert body["sent"] == 0 and body["skipped"] == "no alerts"


def test_dispatch_force_attempts_send_even_when_empty(auth_client, app):
    gid, uid = _ids(app)
    _add_notifier(app, gid, uid)
    r = auth_client.post("/api/v1/notifiers/dispatch?force=1")
    body = r.get_json()
    # apprise isn't installed in tests, so ok=False, but a send was ATTEMPTED
    # for the safe URL (proves the pipeline reaches the sender).
    assert body["attempted"] == 1
    assert body["results"][0]["error"] == "send failed"  # not "blocked"


def test_dispatch_only_sends_to_the_callers_group(auth_client, app, client):
    # User A (auth_client) has a notifier in group A.
    gid_a, uid_a = _ids(app)
    _add_notifier(app, gid_a, uid_a)

    # User B registers → own group; dispatches → no notifiers in B's group.
    client.post("/api/v1/users/register",
                json={"email": "b@b.com", "password": "password", "name": "B"})
    tok = client.post("/api/v1/users/login",
                      json={"username": "b@b.com", "password": "password"}
                      ).get_json()["token"]
    client.environ_base["HTTP_AUTHORIZATION"] = tok
    r = client.post("/api/v1/notifiers/dispatch?force=1")
    assert r.get_json()["attempted"] == 0, "leaked another group's notifier"
