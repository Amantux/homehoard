"""P101: a locked vault shows nothing; an unlock belongs to one credential in one
household; an expired acting key is not a credential.

The failure modes here are all silent (a hidden item quietly listed, one MCP
caller's unlock opening another's vault), so each test asserts the absence
directly and was mutation-checked against the guard it covers.
"""
import json
from datetime import timedelta

import pytest

from app.auth import ACTING_KEY_HEADER
from app.extensions import db
from app.integration_token import ensure_integration_token
from app.models import ApiToken, Item, User, hash_token, utcnow

PHRASE = "open sesame"


def _user(app, email):
    c = app.test_client()
    c.post("/api/v1/users/register",
           json={"email": email, "password": "password", "name": email})
    tok = c.post("/api/v1/users/login",
                 json={"username": email, "password": "password"}).get_json()["token"]
    c.environ_base["HTTP_AUTHORIZATION"] = tok
    return c


def _mint(c, scope="mcp"):
    return c.post("/api/v1/tokens", json={
        "name": scope, "scope": scope, "access": "write",
    }).get_json()["token"]


def _hidden_item(app, c, name, **kw):
    item = c.post("/api/v1/items", json={"name": name, **kw}).get_json()
    with app.app_context():
        db.session.get(Item, item["id"]).hidden = True
        db.session.commit()
    return item


def _call(app, method, path, bearer, acting=None, **kw):
    headers = {"Authorization": f"Bearer {bearer}"}
    if acting is not None:
        headers[ACTING_KEY_HEADER] = acting
    return getattr(app.test_client(), method)(path, headers=headers, **kw)


def _hidden_names(resp):
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return [i["name"] for i in resp.get_json()["items"]]


# (a) ------------------------------------------------------------------------

def test_only_hidden_is_empty_while_locked_and_lists_after_unlock(app, auth_client):
    _hidden_item(app, auth_client, "Secret Telescope")
    assert auth_client.post("/api/v1/vault/passphrase", json={"phrase": PHRASE}).status_code == 200

    assert _hidden_names(auth_client.get("/api/v1/items?onlyHidden=true")) == []

    assert auth_client.post("/api/v1/vault/unlock", json={"phrase": PHRASE}).status_code == 200
    assert _hidden_names(auth_client.get("/api/v1/items?onlyHidden=true")) == ["Secret Telescope"]


# (b) ------------------------------------------------------------------------

@pytest.mark.parametrize("name, basis", [("Secret drill", "similar"), ("saxophone", "popular")])
def test_suggest_placement_never_reveals_a_place_holding_only_hidden_items(
        app, auth_client, name, basis):
    public_bin = auth_client.post("/api/v1/bins", json={"name": "Tool Bin"}).get_json()
    auth_client.post("/api/v1/items", json={"name": "Wrench", "binId": public_bin["id"]})
    secret_loc = auth_client.post("/api/v1/locations", json={"name": "Safe room"}).get_json()
    secret_bin = auth_client.post("/api/v1/bins", json={"name": "Secret Bin"}).get_json()
    _hidden_item(app, auth_client, "Secret drill bits", binId=secret_bin["id"])
    _hidden_item(app, auth_client, "Secret drill", locationId=secret_loc["id"])
    _hidden_item(app, auth_client, "Secret drill press", locationId=secret_loc["id"])

    res = auth_client.get(f"/api/v1/items/suggest-placement?name={name}").get_json()["suggestions"]
    ids = {s["id"] for s in res}
    assert secret_bin["id"] not in ids and secret_loc["id"] not in ids, res
    assert "Secret" not in json.dumps(res)
    if basis == "popular":
        assert res and res[0]["basis"] == "popular" and res[0]["id"] == public_bin["id"]
        assert res[0]["count"] == 1


# (c) ------------------------------------------------------------------------

@pytest.fixture()
def households(app):
    a, b = _user(app, "a@a.com"), _user(app, "b@b.com")
    for c in (a, b):
        assert c.post("/api/v1/vault/passphrase", json={"phrase": PHRASE}).status_code == 200
    _hidden_item(app, a, "Alpha secret")
    _hidden_item(app, b, "Bravo secret")
    integ = ensure_integration_token(app)
    assert integ
    return a, b, integ, _mint(a), _mint(a, scope="full"), _mint(b)


def test_acting_key_unlock_opens_only_that_key_in_that_household(app, households):
    a, b, integ, key_a, key_a2, key_b = households
    r = _call(app, "post", "/api/v1/vault/unlock", integ, acting=key_a, json={"phrase": PHRASE})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _hidden_names(_call(app, "get", "/api/v1/items?onlyHidden=true", integ,
                               acting=key_a)) == ["Alpha secret"]

    # Another household's MCP caller, relayed through the same integration token.
    assert _hidden_names(_call(app, "get", "/api/v1/items?onlyHidden=true", integ,
                               acting=key_b)) == []
    # The integration token on its own (the HA integration).
    assert _hidden_names(_call(app, "get", "/api/v1/items?onlyHidden=true", integ)) == []
    # A's OTHER key: same user, different credential → still locked.
    assert _hidden_names(_call(app, "get", "/api/v1/items?onlyHidden=true", integ,
                               acting=key_a2)) == []
    # And the humans' own sessions were never unlocked.
    assert _hidden_names(a.get("/api/v1/items?onlyHidden=true")) == []
    assert _hidden_names(b.get("/api/v1/items?onlyHidden=true")) == []


def test_unlock_does_not_follow_a_credential_into_another_household(app, households):
    """The unlock row is bound to the household it was made in. If the same
    credential later acts in another household, that household is locked."""
    a, b, *_ = households
    assert a.post("/api/v1/vault/unlock", json={"phrase": PHRASE}).status_code == 200
    with app.app_context():
        ua = db.session.query(User).filter_by(email="a@a.com").one()
        ub = db.session.query(User).filter_by(email="b@b.com").one()
        ua.group_id = ub.group_id
        db.session.commit()
    assert _hidden_names(a.get("/api/v1/items?onlyHidden=true")) == []


# (d) ------------------------------------------------------------------------

def test_expired_acting_key_is_401(app, households):
    _a, _b, integ, key_a, *_ = households
    assert _call(app, "get", "/api/v1/items", integ, acting=key_a).status_code == 200
    with app.app_context():
        rec = db.session.query(ApiToken).filter_by(token_hash=hash_token(key_a)).one()
        rec.expires_at = utcnow() - timedelta(minutes=1)
        db.session.commit()
    assert _call(app, "get", "/api/v1/items", integ, acting=key_a).status_code == 401


# (e) ------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["NaN", "nan", "inf", "-Infinity"])
@pytest.mark.parametrize("field", ["purchasePrice", "soldPrice"])
def test_non_finite_money_is_422(auth_client, field, value):
    r = auth_client.post("/api/v1/items", json={"name": "Lamp", field: value})
    assert r.status_code == 422, r.get_data(as_text=True)
    item = auth_client.post("/api/v1/items", json={"name": "Lamp"}).get_json()
    r = auth_client.patch(f"/api/v1/items/{item['id']}", json={field: value})
    assert r.status_code == 422, r.get_data(as_text=True)
