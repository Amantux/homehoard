"""The notifier digest is actionable: it names what to do AND links where to do it.

Two rules pinned here:
* the restock section obeys never-hidden semantics like the rest of the digest —
  a notification outlives the session, so a hidden consumable stays out EVEN
  WHEN the sender is unlocked;
* tap-through links appear only when PUBLIC_URL is configured (the server can't
  know its browser-facing URL under ingress otherwise), and use hash routes.
"""
from app.extensions import db
from app.models import Group, Item
from app.services.alerts import alert_digest


def _gid(app):
    with app.app_context():
        return db.session.query(Group).first().id


def _item(c, name, **kw):
    return c.post("/api/v1/items", json={"name": name, **kw}).get_json()


def test_digest_includes_low_consumables_with_amounts(auth_client, app):
    _item(auth_client, "AA batteries", quantity=1, minQuantity=4, targetQuantity=12)
    gid = _gid(app)

    with app.app_context():
        digest = alert_digest(gid)

    assert digest["isEmpty"] is False
    assert "AA batteries" in digest["text"]
    assert "11" in digest["text"], "no suggested amount — not actionable"
    assert digest["counts"]["restock"] == 1


def test_hidden_consumable_never_reaches_a_notification_even_unlocked(auth_client, app):
    it = _item(auth_client, "Secret Refill", quantity=0, minQuantity=2)
    with app.app_context():
        db.session.get(Item, it["id"]).hidden = True
        db.session.commit()
    auth_client.post("/api/v1/vault/passphrase", json={"phrase": "open sesame"})
    auth_client.post("/api/v1/vault/unlock", json={"phrase": "open sesame"})

    with app.app_context():
        digest = alert_digest(_gid(app))

    assert "Secret Refill" not in digest["text"]


def test_links_appear_only_when_public_url_is_set(auth_client, app):
    _item(auth_client, "AA batteries", quantity=1, minQuantity=4)
    gid = _gid(app)

    with app.app_context():
        plain = alert_digest(gid)
        app.config["PUBLIC_URL"] = "https://ha.example/api/hassio_ingress/tok"
        linked = alert_digest(gid)
        app.config["PUBLIC_URL"] = ""

    assert "https://" not in plain["text"], "invented a link with no base URL"
    assert "https://ha.example/api/hassio_ingress/tok/#/restock" in linked["text"]


def test_digest_flags_orphaned_rows_and_notifies(auth_client, app):
    from datetime import datetime, timedelta

    from sqlalchemy import text as sql_text

    from app.extensions import db
    from app.models import MaintenanceEntry

    with app.app_context():
        gid = _gid(app)
        it = Item(name="Dryer", group_id=gid)
        db.session.add(it)
        db.session.flush()
        db.session.add(MaintenanceEntry(name="Belt swap", item_id=it.id,
                                       scheduled_date=datetime.utcnow() - timedelta(days=5)))
        db.session.commit()

        clean = alert_digest(gid)
        assert clean["orphans"] == 0
        assert clean["isEmpty"] is False
        assert clean["maintenanceOverdue"][0]["orphan"] is False
        assert "rows point at missing items" not in clean["text"]

        # A maintenance row whose item no longer resolves is an orphan: flag it
        # per-entry, count it, and put the notice into the plain-text digest.
        db.session.execute(sql_text("PRAGMA foreign_keys = OFF"))
        db.session.add(MaintenanceEntry(
            name="Ghost swap",
            item_id="00000000-0000-0000-0000-000000000001",
            scheduled_date=datetime.utcnow() - timedelta(days=3),
        ))
        db.session.commit()
        orphan = alert_digest(gid)
        assert orphan["orphans"] == 1
        ghost = [e for e in orphan["maintenanceOverdue"]
                 if e["itemId"] == "00000000-0000-0000-0000-000000000001"]
        assert len(ghost) == 1 and ghost[0]["orphan"] is True
        assert "1 rows point at missing items." in orphan["text"]
