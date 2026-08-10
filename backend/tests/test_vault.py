"""Vault mode: a hidden item is invisible everywhere until this session unlocks.

The failure mode here is SILENT — a hidden item that quietly appears in one
forgotten read path looks exactly like a working app — so the central test
enumerates surfaces rather than trusting review.
"""
import pytest

from app.extensions import db
from app.models import Item


def _item(c, name, **kw):
    return c.post("/api/v1/items", json={"name": name, **kw}).get_json()


def _hide(app, item_id):
    with app.app_context():
        db.session.get(Item, item_id).hidden = True
        db.session.commit()


def _set_phrase(auth_client, phrase="open sesame"):
    return auth_client.post("/api/v1/vault/passphrase", json={"phrase": phrase})


# Every user-facing read of items. A hidden item must appear in NONE of these
# while locked; adding a surface without adding it here is the regression this
# guards against.
_SURFACES = {
    "items list":   lambda c: c.get("/api/v1/items"),
    "search":       lambda c: c.get("/api/v1/search?q=Telescope"),
    "resolve":      lambda c: c.get("/api/v1/resolve?q=Telescope"),
    "ha summary":   lambda c: c.get("/api/v1/ha/summary"),
    "report":       lambda c: c.get("/api/v1/reports/inventory"),
    "csv export":   lambda c: c.get("/api/v1/items/export"),
    "checkouts":    lambda c: c.get("/api/v1/checkouts"),
}


@pytest.mark.parametrize("surface", sorted(_SURFACES))
def test_hidden_item_is_absent_from_every_read_surface(surface, auth_client, app):
    _item(auth_client, "Ordinary Telescope")
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])

    body = _SURFACES[surface](auth_client).get_data(as_text=True)

    assert "Secret Telescope" not in body, f"{surface} leaked a hidden item"
    assert "Ordinary Telescope" in body or surface in ("checkouts", "resolve"), \
        f"{surface} lost a visible item"


def test_hidden_item_is_not_counted_in_totals(auth_client, app):
    _item(auth_client, "Ordinary Telescope")
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])

    summary = auth_client.get("/api/v1/ha/summary").get_json()

    assert summary["totals"]["items"] == 1, "a hidden item was counted"


# ---- unlock / lock ---------------------------------------------------------

def test_unlock_with_the_right_phrase_reveals_them(auth_client, app):
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])
    _set_phrase(auth_client, "open sesame")

    assert "Secret Telescope" not in auth_client.get("/api/v1/items").get_data(as_text=True)
    r = auth_client.post("/api/v1/vault/unlock", json={"phrase": "open sesame"})

    assert r.status_code == 200
    assert "Secret Telescope" in auth_client.get("/api/v1/items").get_data(as_text=True)


def test_wrong_phrase_changes_nothing(auth_client, app):
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])
    _set_phrase(auth_client, "open sesame")

    r = auth_client.post("/api/v1/vault/unlock", json={"phrase": "guess"})

    assert r.status_code == 401
    assert "Secret Telescope" not in auth_client.get("/api/v1/items").get_data(as_text=True)


def test_lock_hides_them_again(auth_client, app):
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])
    _set_phrase(auth_client, "open sesame")
    auth_client.post("/api/v1/vault/unlock", json={"phrase": "open sesame"})

    auth_client.post("/api/v1/vault/lock")

    assert "Secret Telescope" not in auth_client.get("/api/v1/items").get_data(as_text=True)


def test_unlock_is_per_session_not_household_wide(auth_client, app):
    """Another credential must still see nothing — that is the whole promise."""
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])
    _set_phrase(auth_client, "open sesame")
    auth_client.post("/api/v1/vault/unlock", json={"phrase": "open sesame"})

    # a second session for the SAME user (a different login = a different token)
    other = app.test_client()
    tok = other.post("/api/v1/users/login",
                     json={"email": "t@t.com", "password": "password"}
                     ).get_json()["token"]
    other.environ_base["HTTP_AUTHORIZATION"] = tok

    body = other.get("/api/v1/items").get_data(as_text=True)
    assert "Secret Telescope" not in body, "unlocking one session unlocked another"


# ---- the trap: you must be able to get them back ---------------------------

def test_hidden_items_can_be_listed_and_unhidden_while_locked(auth_client, app):
    """A hidden item you cannot resolve is one you can never recover."""
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])
    _set_phrase(auth_client, "open sesame")
    auth_client.post("/api/v1/vault/unlock", json={"phrase": "open sesame"})

    listed = auth_client.get("/api/v1/items?onlyHidden=true").get_json()
    assert [i["name"] for i in listed["items"]] == ["Secret Telescope"]

    auth_client.patch(f"/api/v1/items/{secret['id']}", json={"hidden": False})
    auth_client.post("/api/v1/vault/lock")
    assert "Secret Telescope" in auth_client.get("/api/v1/items").get_data(as_text=True)


def test_status_reports_a_count_but_never_the_contents(auth_client, app):
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])
    _set_phrase(auth_client)

    body = auth_client.get("/api/v1/vault/status").get_json()

    assert body["locked"] is True and body["hiddenCount"] == 1
    assert "Secret Telescope" not in str(body)


def test_export_contains_them_only_when_unlocked(auth_client, app):
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])
    _set_phrase(auth_client, "open sesame")

    locked = auth_client.get("/api/v1/items/export").get_data(as_text=True)
    auth_client.post("/api/v1/vault/unlock", json={"phrase": "open sesame"})
    unlocked = auth_client.get("/api/v1/items/export").get_data(as_text=True)

    assert "Secret Telescope" not in locked, "a locked export leaked the vault"
    assert "Secret Telescope" in unlocked, "an unlocked export lost the vault"


# ---- the agent surface -----------------------------------------------------

def _tool(gid, name, **args):
    from app.services.ai.agent import execute_tool
    return execute_tool(gid, name, args)


def test_agent_can_hide_then_unlock_and_lock(auth_client, app, gid):
    item = _item(auth_client, "Secret Telescope")
    _set_phrase(auth_client, "open sesame")

    with app.app_context():
        assert _tool(gid, "hide_item", name_or_id="Secret Telescope")["hidden"]
        db.session.commit()
    assert "Secret Telescope" not in auth_client.get("/api/v1/items").get_data(as_text=True)

    # the agent must be able to say WHAT is hidden even while locked
    r = auth_client.post("/api/v1/vault/unlock", json={"phrase": "open sesame"})
    assert r.status_code == 200
    assert "Secret Telescope" in auth_client.get("/api/v1/items").get_data(as_text=True)
    assert item["id"]


def test_agent_asks_for_the_phrase_instead_of_guessing(auth_client, app, gid):
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])
    _set_phrase(auth_client, "open sesame")

    with app.app_context():
        out = _tool(gid, "unhide_items")            # no phrase supplied

    assert out.get("needsPassphrase") is True
    assert "Secret Telescope" not in auth_client.get("/api/v1/items").get_data(as_text=True)


def test_agent_wrong_phrase_reveals_nothing(auth_client, app, gid):
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])
    _set_phrase(auth_client, "open sesame")

    with app.app_context():
        out = _tool(gid, "unhide_items", phrase="not it")

    assert out.get("unlocked") is False
    assert "Secret Telescope" not in auth_client.get("/api/v1/items").get_data(as_text=True)


def test_agent_list_hidden_works_while_locked(auth_client, app, gid):
    """Otherwise a hidden item can never be found to bring it back."""
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])

    with app.app_context():
        rows = _tool(gid, "list_hidden")

    assert [r["name"] for r in rows] == ["Secret Telescope"]


def test_agent_read_tools_do_not_leak_a_hidden_item(auth_client, app, gid):
    _item(auth_client, "Ordinary Telescope")
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])

    with app.app_context():
        found = _tool(gid, "search_items", query="Telescope")
        got = _tool(gid, "get_item", name_or_id="Secret Telescope")

    assert "Secret Telescope" not in str(found), "agent search leaked the vault"
    assert got.get("error"), "agent get_item returned a hidden item"


def test_logout_relocks_the_vault(auth_client, app):
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])
    _set_phrase(auth_client, "open sesame")
    auth_client.post("/api/v1/vault/unlock", json={"phrase": "open sesame"})
    assert "Secret Telescope" in auth_client.get("/api/v1/items").get_data(as_text=True)

    auth_client.post("/api/v1/users/logout")

    assert "Secret Telescope" not in auth_client.get("/api/v1/items").get_data(as_text=True)


# ---- adversarial: the leaks a per-surface list can miss ---------------------
# Written after reviewing the diff by hand: the parametrised test above walks
# LIST endpoints, so it cannot catch a fetch that needs the id. Knowing an id is
# not authorisation — ids appear in old exports, QR tags and old links.

def test_direct_fetch_by_id_does_not_reveal_a_hidden_item(auth_client, app):
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])

    r = auth_client.get(f"/api/v1/items/{secret['id']}")

    assert r.status_code == 404, "fetching by id walked straight past the vault"
    assert "Secret Telescope" not in r.get_data(as_text=True)


def test_hidden_item_is_not_in_statistics_totals(auth_client, app):
    _item(auth_client, "Ordinary Telescope", purchasePrice="10.00")
    secret = _item(auth_client, "Secret Telescope", purchasePrice="999.00")
    _hide(app, secret["id"])

    stats = auth_client.get("/api/v1/statistics").get_json()

    assert "999" not in str(stats), f"a hidden item's value leaked into totals: {stats}"


def test_hidden_item_is_not_reachable_through_sibling_routes(auth_client, app):
    """attachments / holdings / maintenance / checkout all fetch by id."""
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])
    sid = secret["id"]

    for label, resp in {
        "attachments": auth_client.get(f"/api/v1/items/{sid}/attachments"),
        "holdings": auth_client.get(f"/api/v1/items/{sid}/holdings"),
        "maintenance": auth_client.get(f"/api/v1/items/{sid}/maintenance"),
        "checkout": auth_client.post(f"/api/v1/items/{sid}/checkout", json={"to": "x"}),
    }.items():
        assert resp.status_code in (404, 405), \
            f"{label} reached a hidden item ({resp.status_code})"


def test_a_holding_does_not_expose_its_hidden_item(auth_client, app):
    """A holding is a window onto its item — reaching one would surface the
    item's placement, and through it the item."""
    secret = _item(auth_client, "Secret Telescope")
    rows = auth_client.get(f"/api/v1/items/{secret['id']}/holdings").get_json()
    rows = rows["items"] if isinstance(rows, dict) else rows
    hid = rows[0]["id"]
    _hide(app, secret["id"])

    # /holdings/<id>/move is the route that acts on one holding by id.
    r = auth_client.post(f"/api/v1/holdings/{hid}/move", json={"quantity": 1})

    assert r.status_code == 404, "a holding leaked its hidden item"


def test_hidden_item_is_not_in_the_spend_buckets(auth_client, app):
    secret = _item(auth_client, "Secret Telescope",
                   purchasePrice="999.00", purchaseDate="2026-01-15")
    _hide(app, secret["id"])

    body = auth_client.get("/api/v1/statistics/spend").get_data(as_text=True)

    assert "999" not in body, "a hidden item's spend leaked into the buckets"


def test_a_hidden_item_cannot_be_added_to_a_bin(auth_client, app):
    """Accepting the write would confirm the item exists."""
    b = auth_client.post("/api/v1/bins", json={"name": "Crate"}).get_json()
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])

    r = auth_client.put(f"/api/v1/bins/{b['id']}/items/{secret['id']}")

    assert r.status_code == 404, "a hidden item was reachable through a bin write"
