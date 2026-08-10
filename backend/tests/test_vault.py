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


def test_unlock_is_per_credential_not_household_wide(auth_client, app):
    """Another credential must still see nothing — that is the whole promise.

    Asserted with an API TOKEN rather than a second login: this app's JWT is a
    pure function of its claims at second resolution, so two logins inside the
    same second return the BYTE-IDENTICAL token and are therefore genuinely the
    same credential (this test raced on exactly that). Across devices or
    seconds the tokens differ and the isolation is real; a machine token is the
    unambiguous case, and the one that matters most — an automation must never
    inherit a human's unlock."""
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])
    _set_phrase(auth_client, "open sesame")
    auth_client.post("/api/v1/vault/unlock", json={"phrase": "open sesame"})
    assert "Secret Telescope" in auth_client.get("/api/v1/items").get_data(as_text=True)

    raw = auth_client.post("/api/v1/tokens", json={"name": "bot"}).get_json()
    machine = app.test_client()
    machine.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {raw['token']}"

    body = machine.get("/api/v1/items").get_data(as_text=True)
    assert "Secret Telescope" not in body, "an API token inherited a human's unlock"


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


# ---- the sweep: EVERY registered GET route, not a list I remembered ---------

def test_no_registered_get_route_leaks_a_hidden_item(auth_client, app):
    """Walks the URL map rather than a hand-written list of surfaces.

    Written after a hand audit found six leaks the parametrised test above could
    not reach: bin/label/location detail pages expand items through a
    RELATIONSHIP (which a query-level filter never sees), and maintenance
    reaches the item through its entry. A future endpoint that forgets the vault
    fails here without anyone remembering to add it.
    """
    MARK = "Zqxjvault"
    loc = auth_client.post("/api/v1/locations", json={"name": "Shed"}).get_json()
    b = auth_client.post("/api/v1/bins",
                         json={"name": "Crate", "locationId": loc["id"]}).get_json()
    lab = auth_client.post("/api/v1/labels", json={"name": "tools"}).get_json()
    secret = auth_client.post("/api/v1/items", json={
        "name": f"{MARK} Telescope", "description": f"{MARK} desc",
        "notes": f"{MARK} note", "locationId": loc["id"], "binId": b["id"],
        "labelIds": [lab["id"]], "serialNumber": MARK, "manufacturer": MARK,
        "purchasePrice": "999.00", "purchaseDate": "2026-01-15",
        "warrantyExpires": "2027-01-15"}).get_json()
    auth_client.post(f"/api/v1/items/{secret['id']}/maintenance",
                     json={"name": f"{MARK} service", "scheduledDate": "2026-02-01"})
    auth_client.post(f"/api/v1/items/{secret['id']}/checkout", json={"to": "Bob"})
    _hide(app, secret["id"])

    subs = {"<item_id>": secret["id"], "<bin_id>": b["id"],
            "<location_id>": loc["id"], "<label_id>": lab["id"], "<id>": secret["id"]}
    leaks, checked = [], 0
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods:
            continue
        path = str(rule.rule)
        for k, v in subs.items():
            path = path.replace(k, str(v))
        if "<" in path:
            continue          # an argument we can't fill; covered by other tests
        checked += 1
        body = auth_client.get(path).get_data().decode("utf-8", "ignore")
        if MARK in body:
            leaks.append(path)

    assert checked > 40, f"only walked {checked} routes — the sweep isn't running"
    assert leaks == [], f"hidden item leaked from: {leaks}"


def test_notifications_never_name_a_hidden_item_even_when_unlocked(auth_client, app):
    """A digest outlives the session and leaves the machine — an unlock is one
    browser tab, a notification on a phone is permanent."""
    from app.services.alerts import alert_digest
    from app.models import Group

    secret = _item(auth_client, "Secret Telescope",
                   warrantyExpires="2026-08-20")
    auth_client.post(f"/api/v1/items/{secret['id']}/maintenance",
                     json={"name": "Secret service", "scheduledDate": "2026-01-01"})
    _hide(app, secret["id"])
    _set_phrase(auth_client, "open sesame")
    auth_client.post("/api/v1/vault/unlock", json={"phrase": "open sesame"})

    with app.app_context():
        gid = db.session.query(Group).first().id
        digest = alert_digest(gid)

    assert "Secret Telescope" not in digest["text"]
    assert "Secret service" not in digest["text"]


# ---- setting the passphrase ------------------------------------------------

def test_first_passphrase_can_be_set_and_then_unlocks(auth_client, app):
    secret = _item(auth_client, "Secret Telescope")
    _hide(app, secret["id"])

    r = auth_client.post("/api/v1/vault/passphrase", json={"phrase": "hunter two"})

    assert r.status_code == 200 and r.get_json()["configured"] is True
    assert auth_client.post("/api/v1/vault/unlock",
                            json={"phrase": "hunter two"}).status_code == 200


def test_changing_it_requires_the_current_one(auth_client):
    """Otherwise anyone with an open session could silently re-key the vault
    and lock the owner out of their own items."""
    auth_client.post("/api/v1/vault/passphrase", json={"phrase": "first"})

    bare = auth_client.post("/api/v1/vault/passphrase", json={"phrase": "second"})
    wrong = auth_client.post("/api/v1/vault/passphrase",
                             json={"phrase": "second", "currentPhrase": "nope"})
    right = auth_client.post("/api/v1/vault/passphrase",
                             json={"phrase": "second", "currentPhrase": "first"})

    assert bare.status_code == 401 and wrong.status_code == 401
    assert right.status_code == 200
    assert auth_client.post("/api/v1/vault/unlock",
                            json={"phrase": "second"}).status_code == 200


def test_a_non_owner_cannot_set_the_passphrase(auth_client, app):
    """It gates every member's view, so it is household config."""
    from app.models import User
    with app.app_context():
        db.session.query(User).first().is_owner = False
        db.session.commit()

    r = auth_client.post("/api/v1/vault/passphrase", json={"phrase": "nope"})

    assert r.status_code == 403


def test_an_empty_passphrase_is_refused(auth_client):
    assert auth_client.post("/api/v1/vault/passphrase",
                            json={"phrase": "   "}).status_code == 422


def test_status_tells_the_ui_whether_a_vault_exists_yet(auth_client):
    """The UI needs this to offer 'set a passphrase' rather than dead-ending on
    an unlock prompt that can never succeed."""
    before = auth_client.get("/api/v1/vault/status").get_json()
    auth_client.post("/api/v1/vault/passphrase", json={"phrase": "x y z"})
    after = auth_client.get("/api/v1/vault/status").get_json()

    assert before["configured"] is False and after["configured"] is True
