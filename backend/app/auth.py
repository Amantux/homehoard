"""Authentication layer.

Supports two modes:

* **Enabled** (default): JWT bearer tokens issued at login. Requests must send
  ``Authorization: Bearer <token>``.
* **Disabled** (``HBOX_DISABLE_AUTH=true``): every request is transparently
  bound to a default user/group. This is intended for running behind Home
  Assistant ingress, which already authenticates the user.
"""
import functools
import logging
import secrets
from datetime import datetime, timezone

import jwt
from flask import current_app, g, request, jsonify
from passlib.hash import bcrypt

from .extensions import db
from .logsafe import scrub
from .models import User, Group, ApiToken, hash_token
from .models.api_token import TOKEN_PREFIX

_LOGGER = logging.getLogger("homehoard.auth")

DEFAULT_EMAIL = "local@easyinventory"
DEFAULT_GROUP = "Home"


def hash_password(password: str) -> str:
    return bcrypt.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.verify(password, hashed)
    except (ValueError, TypeError):
        return False


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user.id, "iat": now, "exp": now + current_app.config["JWT_EXPIRES"]}
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def decode_token(token: str):
    try:
        payload = jwt.decode(
            token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
        )
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def _default_user() -> User:
    """Return (creating if needed) the single local user for no-auth mode."""
    user = db.session.query(User).filter_by(email=DEFAULT_EMAIL).first()
    if user:
        return user
    # JOIN the shared household — the earliest-created group, the same one
    # ingress users are provisioned into — rather than minting a fresh one. A
    # machine client bound to this user (the HA integration token) would
    # otherwise read a different, empty household than the real HA users
    # populate. Only seed a brand-new household when none exists yet.
    group = db.session.query(Group).order_by(Group.created_at.asc()).first()
    if group is None:
        group = Group(name=DEFAULT_GROUP, currency="usd")
        db.session.add(group)
        db.session.flush()
    user = User(
        name="Local User",
        email=DEFAULT_EMAIL,
        # A random, discarded password — this account is never meant to be
        # reachable through /users/login (it exists only as the DISABLE_AUTH
        # fallback identity and the anchor the integration token binds to). A
        # fixed literal here would be a public, guessable password for an
        # owner account on every install, including hardened (DISABLE_AUTH=false)
        # ones where the integration token is minted at startup regardless.
        password_hash=hash_password(secrets.token_urlsafe(32)),
        is_owner=True,
        group_id=group.id,
    )
    db.session.add(user)
    db.session.commit()
    return user


# Ingress requests reach the add-on FROM the HA Supervisor, whose address on the
# hassio network is 172.30.32.2. Trust the X-Remote-User-* identity headers ONLY
# from that exact peer — NOT the whole 172.30.32.0/23 (the SNAT gateway .1 is in
# range, so a /23 check would trust forged headers from a host-published port).
# We read the UNPROXIED TCP peer (ProxyFix rewrites request.remote_addr from
# X-Forwarded-For when PROXY_HOPS>0), so a client-supplied XFF can't spoof the
# Supervisor address. Fail-closed: an unrecognised peer → shared local user.
_INGRESS_SOURCE = "172.30.32.2"


def _raw_peer():
    orig = request.environ.get("werkzeug.proxy_fix.orig")
    if orig and orig.get("REMOTE_ADDR"):
        return orig["REMOTE_ADDR"]
    return request.remote_addr


def _request_from_ingress() -> bool:
    return _raw_peer() == _INGRESS_SOURCE


def _ingress_user():
    """Provision (or fetch) the HomeHoard user for the HA user behind an ingress
    request. Returns None with no trusted ingress identity, so the caller falls
    back to the shared local user. All HA users share one household; the first
    REAL HA user seen becomes owner."""
    if not _request_from_ingress():
        return None
    ha_id = (request.headers.get("X-Remote-User-Id") or "").strip()
    if not ha_id:
        return None

    user = db.session.query(User).filter_by(ha_user_id=ha_id).first()
    real_name = (request.headers.get("X-Remote-User-Display-Name")
                 or request.headers.get("X-Remote-User-Name") or "").strip()
    if user:
        if real_name and user.name != real_name:
            user.name = real_name
            db.session.commit()
        return user

    group = db.session.query(Group).order_by(Group.created_at.asc()).first()
    if group is None:
        group = Group(name=DEFAULT_GROUP, currency="usd")
        db.session.add(group)
        db.session.flush()
    # Count owners among REAL HA users only, so a legacy synthetic local user
    # (ha_user_id NULL, is_owner True) doesn't lock the first real HA user out.
    has_owner = db.session.query(User).filter(
        User.group_id == group.id,
        User.is_owner.is_(True),
        User.ha_user_id.isnot(None),
    ).count() > 0
    user = User(name=real_name or "Home Assistant user",
                email=f"ha:{ha_id}",
                # Random, discarded — this account authenticates only via the
                # trusted ingress header, never via /users/login.
                password_hash=hash_password(secrets.token_urlsafe(32)),
                is_owner=not has_owner, ha_user_id=ha_id, group_id=group.id)
    db.session.add(user)
    db.session.commit()
    return user


def load_current_user():
    """Resolve the current user from three INDEPENDENT sources, in order — so a
    machine client (the HA integration, MCP) can authenticate by token whether or
    not DISABLE_AUTH is set, while the browser keeps working behind ingress.
    DISABLE_AUTH then only controls the open fallback (step 3).

    1. An explicit ``Authorization: Bearer`` token — a long-lived API key or a
       login JWT. A present-but-INVALID token is a 401, never a silent downgrade
       to the shared user.
    2. A trusted HA ingress identity (``X-Remote-User-*`` from the Supervisor
       peer), provisioning the per-HA-user account. This runs REGARDLESS of
       DISABLE_AUTH — that's what makes a hardened install (disable_auth: false)
       usable behind ingress; previously this branch never ran with auth
       enabled, so a browser behind ingress got 401'd in hardened mode.
    3. In open mode (DISABLE_AUTH) only: the shared local user — covering both a
       standalone open deployment and an ingress request with no identity
       headers.
    """
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        token = header[len("Bearer "):].strip()
        # Long-lived API keys are prefixed so we can route them without a JWT decode.
        if token.startswith(TOKEN_PREFIX):
            return _user_from_api_token(token)
        user_id = decode_token(token)
        return db.session.get(User, user_id) if user_id else None

    ingress = _ingress_user()
    if ingress is not None:
        return ingress

    if current_app.config["DISABLE_AUTH"]:
        return _default_user()

    return None


def _user_from_api_token(raw: str):
    record = (
        db.session.query(ApiToken)
        .filter_by(token_hash=hash_token(raw))
        .first()
    )
    if record is None:
        return None
    # Scope gate: `mcp` keys are issued for the MCP transport alone and `debug`
    # keys for the MCP debug tools alone — neither may authenticate the REST API.
    # `full`/`rest` (and legacy NULL→"full") pass. This is the one place the
    # scope is checked for REST, so a new scope is denied here or nowhere.
    if (record.scope or "full") in ("mcp", "debug"):
        return None
    # Access class: a read-only key may authenticate but is limited to safe methods
    # (enforced in login_required/owner_required). Stash it for that check.
    g.token_access = record.access or "write"
    # Record usage, but at most once a minute to avoid a write on every request.
    now = datetime.utcnow()
    if record.last_used_at is None or (now - record.last_used_at).total_seconds() > 60:
        record.last_used_at = now
        db.session.commit()
    return db.session.get(User, record.user_id)


def _read_only_blocked():
    """A read-only API key may only make safe requests. Returns a 403 response for a
    mutating method, else None. No-op for JWT/ingress users (no token → default write)."""
    if getattr(g, "token_access", "write") == "read" and \
            request.method not in ("GET", "HEAD", "OPTIONS"):
        return jsonify({"error": "this API key is read-only"}), 403
    return None


def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = load_current_user()
        if user is None:
            _LOGGER.warning(
                "unauthorized %s %s from %s",
                scrub(request.method), scrub(request.path), scrub(request.remote_addr),
            )
            return jsonify({"error": "unauthorized"}), 401
        blocked = _read_only_blocked()
        if blocked:
            return blocked
        g.current_user = user
        g.current_group = user.group
        return fn(*args, **kwargs)

    return wrapper


def owner_required(fn):
    """Like login_required, but 403s a non-owner — for household config members
    shouldn't change (API keys, notifiers)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = load_current_user()
        if user is None:
            return jsonify({"error": "unauthorized"}), 401
        if not user.is_owner:
            return jsonify({"error": "owner privileges required"}), 403
        blocked = _read_only_blocked()
        if blocked:
            return blocked
        g.current_user = user
        g.current_group = user.group
        return fn(*args, **kwargs)

    return wrapper


def current_user() -> User:
    return g.current_user


def current_group() -> Group:
    return g.current_group
