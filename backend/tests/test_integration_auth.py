"""Auth-resolution + integration-token behaviour for the companion HA integration.

The integration polls the REST API directly (not via ingress), so a Bearer API
key must authenticate it in EVERY mode, and the minted token must be stable and
bound to the household the ingress users share.
"""
import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.integration_token import TOKEN_NAME, ensure_integration_token

SUMMARY = "/api/v1/ha/summary"          # auth-gated poll endpoint (login_required)
SUP = {"REMOTE_ADDR": "172.30.32.2"}    # the Supervisor ingress peer
LAN = {"REMOTE_ADDR": "192.168.1.50"}   # an untrusted direct-port client


@pytest.fixture()
def noauth_app(tmp_path):
    """DISABLE_AUTH (ingress/open) mode."""
    class C(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = f"sqlite:///{tmp_path}/na.db"
        DISABLE_AUTH = True
        SECRET_KEY = "test-secret-key-that-is-long-enough-32b"
        RATELIMIT_ENABLED = False
        PROXY_HOPS = 0

    app = create_app(C)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


# --- Bearer is authoritative even when auth is "disabled" -------------------

def test_invalid_api_key_under_disable_auth_returns_401(noauth_app):
    # Regression guard: a present-but-invalid Bearer must NOT silently downgrade
    # to the shared user just because DISABLE_AUTH is set.
    client = noauth_app.test_client()

    prefixed = client.get(SUMMARY, headers={"Authorization": "Bearer hbox_not_a_real_key"})
    junk = client.get(SUMMARY, headers={"Authorization": "Bearer totally-bogus"})

    assert prefixed.status_code == 401
    assert junk.status_code == 401


def test_valid_api_key_under_disable_auth_returns_200(noauth_app):
    raw = ensure_integration_token(noauth_app)
    client = noauth_app.test_client()

    resp = client.get(SUMMARY, headers={"Authorization": f"Bearer {raw}"})

    assert resp.status_code == 200


# --- Ingress identity works independently of the DISABLE_AUTH toggle --------

def test_ingress_identity_honored_when_auth_enabled(client):
    # DISABLE_AUTH is False here (the default `app`/`client` fixture); a
    # trusted-peer ingress request must resolve an identity — this was the bug:
    # the DISABLE_AUTH branch short-circuited BEFORE the ingress check, so a
    # hardened install 401'd every browser request behind ingress.
    resp = client.get(
        SUMMARY,
        headers={"X-Remote-User-Id": "ha-abc", "X-Remote-User-Display-Name": "Alex"},
        environ_overrides=SUP,
    )

    assert resp.status_code == 200


def test_forged_ingress_headers_from_untrusted_peer_rejected(client):
    # The same identity headers from a non-Supervisor address must not authenticate.
    resp = client.get(
        SUMMARY,
        headers={"X-Remote-User-Id": "ha-abc", "X-Remote-User-Display-Name": "Alex"},
        environ_overrides=LAN,
    )

    assert resp.status_code == 401


def test_forged_xforwarded_for_supervisor_rejected(tmp_path):
    # The trust boundary reads the UNPROXIED TCP peer (_raw_peer), so even with a
    # proxy configured (PROXY_HOPS=1, as the add-on sets), a client-supplied
    # X-Forwarded-For claiming the Supervisor address cannot spoof ingress trust.
    class ProxyConfig(Config):
        DATA_DIR = str(tmp_path)
        DATABASE_URL = f"sqlite:///{tmp_path}/proxy.db"
        DISABLE_AUTH = False
        PROXY_HOPS = 1
        SECRET_KEY = "test-secret-key-that-is-long-enough-32b"
        RATELIMIT_ENABLED = False

    proxy_app = create_app(ProxyConfig)
    try:
        resp = proxy_app.test_client().get(
            SUMMARY,
            headers={"X-Remote-User-Id": "ha-1", "X-Remote-User-Display-Name": "Alex",
                     "X-Forwarded-For": "172.30.32.2"},
            environ_overrides=LAN,     # true TCP peer is the untrusted LAN client
        )
        assert resp.status_code == 401
    finally:
        with proxy_app.app_context():
            db.session.remove()
            db.drop_all()


# --- Minted integration token ----------------------------------------------

def test_ensure_integration_token_is_stable(app):
    first = ensure_integration_token(app)
    second = ensure_integration_token(app)

    assert first and first.startswith("hh_")
    assert first == second  # reused, not rotated on the second call


def test_ensure_integration_token_authenticates(app):
    raw = ensure_integration_token(app)
    client = app.test_client()

    resp = client.get(SUMMARY, headers={"Authorization": f"Bearer {raw}"})

    assert resp.status_code == 200


def test_integration_token_is_named_and_revocable(app):
    ensure_integration_token(app)
    from app.models import ApiToken

    with app.app_context():
        rows = db.session.query(ApiToken).filter_by(name=TOKEN_NAME).all()

    assert len(rows) == 1  # exactly one, and it shows up in Settings → API keys


def test_integration_token_binds_to_ingress_household(client, app):
    # Regression for the group-divergence bug: an HA user provisioned via ingress
    # FIRST creates the household group; the integration token minted afterwards
    # must land in that SAME group, or the integration reads an empty household.
    client.get(  # provision the ingress user (and its group) first
        SUMMARY,
        headers={"X-Remote-User-Id": "ha-1", "X-Remote-User-Display-Name": "Alex"},
        environ_overrides=SUP,
    )
    raw = ensure_integration_token(app)

    from app.models import ApiToken, Group, User, hash_token

    with app.app_context():
        ingress_user = db.session.query(User).filter_by(ha_user_id="ha-1").first()
        token = db.session.query(ApiToken).filter_by(token_hash=hash_token(raw)).first()

        assert db.session.query(Group).count() == 1  # no second household minted
        assert token.group_id == ingress_user.group_id


def test_integration_token_binds_household_when_minted_first(app):
    # The REAL startup order: the entrypoint mints the token BEFORE any HA user
    # exists, so _default_user creates the household group; a later ingress user
    # must JOIN it (and become owner), not fork a second household.
    raw = ensure_integration_token(app)
    ic = app.test_client()
    ic.get(  # first ingress user arrives after the token was minted
        SUMMARY,
        headers={"X-Remote-User-Id": "ha-late", "X-Remote-User-Display-Name": "Alex"},
        environ_overrides=SUP,
    )

    from app.models import ApiToken, Group, User, hash_token

    with app.app_context():
        ha_user = db.session.query(User).filter_by(ha_user_id="ha-late").first()
        token = db.session.query(ApiToken).filter_by(token_hash=hash_token(raw)).first()

        assert db.session.query(Group).count() == 1          # one shared household
        assert token.group_id == ha_user.group_id            # token + HA user converge
        assert ha_user.is_owner is True                      # first real HA user owns it


def test_default_user_password_is_not_a_known_login_backdoor(app):
    # Regression: the account _default_user()/_ingress_user() synthesize must
    # NOT be reachable via a plain password login — it's minted at startup on
    # every Supervisor-run install (open OR hardened) so the integration token
    # has a household to bind to, and a fixed literal password would be a
    # public, guessable owner login on every install.
    ensure_integration_token(app)
    client = app.test_client()

    resp = client.post(
        "/api/v1/users/login",
        json={"username": "local@easyinventory", "password": "unused"},
    )

    assert resp.status_code == 401


def test_preexisting_backdoor_password_is_rotated_on_upgrade(app):
    # Installs that ran BEFORE this fix already have a local@easyinventory row
    # with the literal "unused" password persisted in their database —
    # rotating the password only in the create branch would leave every such
    # upgrade exposed forever, since _default_user()/_ingress_user() just
    # return the existing row. Simulate that pre-existing state and confirm
    # it heals.
    from app.auth import DEFAULT_EMAIL, hash_password
    from app.models import Group, User

    with app.app_context():
        group = Group(name="Home", currency="usd")
        db.session.add(group)
        db.session.flush()
        db.session.add(User(name="Local User", email=DEFAULT_EMAIL,
                             password_hash=hash_password("unused"),
                             is_owner=True, group_id=group.id))
        db.session.commit()

    client = app.test_client()
    still_works = client.post(
        "/api/v1/users/login",
        json={"username": DEFAULT_EMAIL, "password": "unused"},
    )
    assert still_works.status_code == 200  # sanity: the seeded state is exploitable

    from app.auth import _default_user
    with app.app_context():
        _default_user()  # e.g. the startup integration-token mint resolving it

    healed = client.post(
        "/api/v1/users/login",
        json={"username": DEFAULT_EMAIL, "password": "unused"},
    )
    assert healed.status_code == 401


def test_valid_jwt_authenticates_through_reordered_branch(client):
    client.post(
        "/api/v1/users/register",
        json={"email": "j@j.com", "password": "password", "name": "J"},
    )
    token = client.post(
        "/api/v1/users/login", json={"username": "j@j.com", "password": "password"}
    ).get_json()["token"]

    resp = client.get(SUMMARY, headers={"Authorization": token})

    assert resp.status_code == 200
