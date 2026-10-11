"""Authentication layer.

Supports two modes:

* **Enabled** (default): JWT bearer tokens issued at login. Requests must send
  ``Authorization: Bearer <token>``.
* **Disabled** (``HBOX_DISABLE_AUTH=true``): every request is transparently
  bound to a default user/group. This is intended for running behind Home
  Assistant ingress, which already authenticates the user.
"""
import contextlib
import functools
import logging
import os
import secrets
from datetime import datetime, timezone

import jwt
from flask import current_app, g, request, jsonify
from passlib.hash import bcrypt
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .backup_guard import BackupInProgress
from .extensions import db
from .logging_setup import request_id_var
from .logsafe import scrub
from .models import User, Group, ApiToken, hash_token
from .models.api_token import TOKEN_PREFIX
from .integration_token import TOKEN_NAME as _INTEGRATION_TOKEN_NAME, _raw_path
from .timeutil import as_utc, utcnow

# The MCP sidecar calls REST with the integration token and names the MCP
# caller's own key here, so the call acts as THAT key's user and access class.
ACTING_KEY_HEADER = "X-HBOX-Acting-Key"

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


def _user_from_jwt(token: str):
    """The user a JWT names, or None when it is invalid — including when it was
    issued before the user's last password change (that change signs out every
    older session). ``iat`` is whole seconds (PyJWT truncates), so the change
    instant is truncated too: a token minted in the same second as the change —
    the one change-password hands back — stays valid."""
    try:
        payload = jwt.decode(
            token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
        )
    except jwt.PyJWTError:
        return None
    user_id = payload.get("sub")
    user = db.session.get(User, user_id) if user_id else None
    if user is None:
        return None
    changed = as_utc(user.password_changed_at)
    if changed is not None:
        iat = payload.get("iat")
        # Fail closed: a token with no usable iat can't prove it postdates the change.
        if not isinstance(iat, (int, float)) or iat < int(changed.timestamp()):
            return None
    return user


# A version before this fix minted synthetic users with this literal password,
# which /users/login's ungated email+password check made a public, guessable
# owner-login backdoor. Rotating it only in the CREATE branch below would leave
# every already-provisioned install exposed forever — the row already exists,
# so _default_user/_ingress_user just return it. Detect and rotate it here, on
# every read, so an upgrade closes the door without a migration.
_KNOWN_BACKDOOR_PASSWORD = "unused"


# (user.id, password_hash) pairs already proven NOT to be the backdoor. A bcrypt
# verify costs ~250 ms and this runs on every open-mode/ingress request, so check
# each pair once per worker. Keyed on the hash, so any rotation or password
# change produces a new key and is re-checked once; bounded by users x changes.
_ROTATION_CHECKED: set[tuple[int, str]] = set()


def _rotate_known_backdoor_password(user: User) -> None:
    if (user.id, user.password_hash) in _ROTATION_CHECKED:
        return
    if verify_password(_KNOWN_BACKDOOR_PASSWORD, user.password_hash):
        user.password_hash = hash_password(secrets.token_urlsafe(32))
        try:
            db.session.commit()
        except (SQLAlchemyError, BackupInProgress):
            # A read must not fail on this bookkeeping (e.g. during an HA
            # backup). Not recorded as checked, so the next request retries.
            db.session.rollback()
            return
    _ROTATION_CHECKED.add((user.id, user.password_hash))


@contextlib.contextmanager
def _group_bootstrap_lock():
    """Serialize the check-then-maybe-create-Group step across gunicorn's worker
    PROCESSES (a Python lock only covers threads within one). Two concurrent
    first-load requests hitting different workers could otherwise both observe
    zero groups and each insert one — Group has no unique constraint to catch
    that. Mirrors the fcntl file lock _init_schema() takes at boot, but taken
    per-call since this runs at request time."""
    import fcntl
    lock_path = os.path.join(current_app.config["DATA_DIR"], ".group-bootstrap.lock")
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass  # locking unsupported (rare FS) — best-effort only.
        try:
            yield
        finally:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def _group_race_probe():
    """Test seam only: called right after reading the existing-household state,
    while (in production) still holding _group_bootstrap_lock(). A test can use
    this to hold one caller here and let a second, UNLOCKED caller run the same
    read concurrently, proving the lock — not luck — is what stops two
    households from being created. No-op in production."""


def _resolve_bootstrap_group() -> Group:
    """The household a synthetic/service account (the shared local user, or an
    anonymous ingress/HA account) should join. Joining "the earliest-created
    group" is only a safe guess when it's the ONLY group that exists — once
    self-registration has produced more than one household, guessing which is
    the operator's real one would let a machine-bound account (the HA
    integration token) or an open-mode ingress user become an owner inside a
    stranger's household. When that ambiguity already exists, give the
    synthetic account its own new household instead of guessing. Caller must
    hold _group_bootstrap_lock()."""
    existing = db.session.query(Group).order_by(Group.created_at.asc()).limit(2).all()
    _group_race_probe()
    if len(existing) == 1:
        return existing[0]
    if existing:
        _LOGGER.warning(
            "Multiple households already exist; provisioning a separate "
            "household for a synthetic/service account instead of guessing "
            "which existing one belongs to the operator."
        )
    group = Group(name=DEFAULT_GROUP, currency="usd")
    db.session.add(group)
    # COMMIT, not just flush: the next caller to take _group_bootstrap_lock()
    # queries from ITS OWN session, which — being a separate DB transaction —
    # cannot see this row until it's committed. A flush-only row is invisible
    # to that re-query, so the lock would hand off cleanly but the second
    # caller would still create a second household.
    db.session.commit()
    return group


def _default_user() -> User:
    """Return (creating if needed) the single local user for no-auth mode."""
    user = db.session.query(User).filter_by(email=DEFAULT_EMAIL).first()
    if user:
        _rotate_known_backdoor_password(user)
        return user
    # JOIN the shared household — the earliest-created group, the same one
    # ingress users are provisioned into — rather than minting a fresh one. A
    # machine client bound to this user (the HA integration token) would
    # otherwise read a different, empty household than the real HA users
    # populate.
    with _group_bootstrap_lock():
        group = _resolve_bootstrap_group()
    # Concurrency-safe: several first-load requests can race to create the shared
    # local user. Let one win; the losers roll back and re-read the winner's row
    # (a UNIQUE violation on users.email would otherwise 500 the request).
    try:
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
    except IntegrityError:
        db.session.rollback()
        return db.session.query(User).filter_by(email=DEFAULT_EMAIL).first()


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


# Open-mode exposure warning: DISABLE_AUTH is meant for HA ingress only, so a
# request that reaches the open-mode fallback from any other peer means the port
# is published off the Home Assistant network. Warn once per peer per process.
# The set is bounded (no new dependency, no unbounded growth from a scan): once
# _OPEN_MODE_WARNED_CAP peers have been recorded, further NEW peers are not
# added and not warned about — the log already shows the exposure many times.
_OPEN_MODE_WARNED: set[str] = set()
_OPEN_MODE_WARNED_CAP = 256
# Loopback is expected: the Docker healthcheck and the MCP sidecar call the API
# from inside the container.
_LOOPBACK_PEERS = frozenset({"127.0.0.1", "::1"})


def _warn_open_mode_exposure() -> None:
    peer = _raw_peer() or "unknown"
    if peer == _INGRESS_SOURCE or peer in _LOOPBACK_PEERS:
        return
    if peer in _OPEN_MODE_WARNED or len(_OPEN_MODE_WARNED) >= _OPEN_MODE_WARNED_CAP:
        return
    _OPEN_MODE_WARNED.add(peer)
    _LOGGER.warning(
        "unauthenticated access from %s: disable_auth is on and the port is "
        "reachable off the Home Assistant network — anyone who can reach it is "
        "the household owner",
        scrub(peer),
    )


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
        _rotate_known_backdoor_password(user)
        if real_name and user.name != real_name:
            user.name = real_name
            try:
                db.session.commit()
            except (SQLAlchemyError, BackupInProgress):
                # Cosmetic refresh; skip it rather than fail the request (e.g.
                # during an HA backup). The next request retries.
                db.session.rollback()
        return user

    with _group_bootstrap_lock():
        group = _resolve_bootstrap_group()
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
    # Race-safe: parallel first-load requests from one HA user can collide on the
    # ha_user_id/email unique index — let one win, re-read for the rest.
    try:
        db.session.commit()
        return user
    except IntegrityError:
        db.session.rollback()
        return db.session.query(User).filter_by(ha_user_id=ha_id).first()
    except BackupInProgress:
        # A brand-new HA user's first load during a backup (seconds long) can't
        # be provisioned read-only: roll back and let the curated 503 answer.
        db.session.rollback()
        raise


def load_current_user():
    """Resolve the current user once per request; the read-only hook and the
    route decorator both ask, and resolution may hit the DB (key lookup, ingress
    provisioning). See _resolve_current_user for the sources."""
    if "_auth_user" not in g:
        g._auth_user = _resolve_current_user()
    return g._auth_user


def _resolve_current_user():
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
    # Only an API key can be read-only; it overwrites this. JWT, ingress and the
    # open-mode fallback are explicitly write.
    g.token_access = "write"
    header = request.headers.get("Authorization", "")
    # An acting key is honoured ONLY alongside the integration token (checked in
    # _user_from_api_token). With no Bearer, or a JWT, it is a 401 — never
    # silently ignored, or the call would run as ingress/open-mode instead.
    acting = request.headers.get(ACTING_KEY_HEADER) is not None
    if header.strip():
        token = _bearer_token(header)
        # Any credential that isn't a Bearer token (wrong scheme, empty token)
        # is "present but invalid" → 401, never a fall-through to ingress or
        # the open-mode user. Otherwise `bearer <read-key>` escalated to write.
        if not token:
            return None
        # Long-lived API keys are prefixed so we can route them without a JWT decode.
        if token.startswith(TOKEN_PREFIX):
            return _user_from_api_token(token)
        if acting:
            return None
        return _user_from_jwt(token)

    if acting:
        return None

    ingress = _ingress_user()
    if ingress is not None:
        return ingress

    if current_app.config["DISABLE_AUTH"]:
        _warn_open_mode_exposure()
        return _default_user()

    return None


def _bearer_token(header: str) -> str | None:
    """The token from an ``Authorization: Bearer <token>`` header, or None when the
    scheme isn't Bearer. The scheme is case-insensitive (RFC 7235); both the
    resolver and the central read-only hook go through here so they can't
    disagree about what counts as a Bearer credential."""
    scheme, _, token = header.strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


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
    # Expiry: past expires_at the key is no longer a credential — 401 like an
    # unknown key, not 403. Checked before the acting-key branch so an expired
    # integration key can't act for anyone either.
    if record.expires_at is not None and as_utc(record.expires_at) <= utcnow():
        return None
    if request.headers.get(ACTING_KEY_HEADER) is not None:
        # Fail closed: any problem with the acting key is a 401, never a
        # fallback to the integration token's own (shared-household) identity.
        if not _is_integration_record(record):
            return None
        return _user_from_acting_key(request.headers.get(ACTING_KEY_HEADER, ""))
    # Access class: a read-only key may authenticate but is limited to safe methods
    # (enforced in login_required/owner_required). Stash it for that check.
    g.token_access = record.access or "write"
    # Record usage, but at most once a minute to avoid a write on every request.
    now = utcnow()
    if record.last_used_at is None or (now - as_utc(record.last_used_at)).total_seconds() > 60:
        record.last_used_at = now
        # Usage bookkeeping only: a failed write (locked SQLite, DB blip) must
        # not turn an otherwise valid token into a 500. Roll back and carry on.
        try:
            db.session.commit()
        except (SQLAlchemyError, BackupInProgress) as exc:
            db.session.rollback()
            _LOGGER.warning("api token last_used_at update failed: %s", type(exc).__name__)
    return db.session.get(User, record.user_id)


def _is_integration_record(record) -> bool:
    """True only for THE integration token: right name and scope, AND its hash
    matches the raw token persisted in the data dir. A name is user-chosen (any
    user can mint a key called "Home Assistant integration"), so the file match
    is what makes this unforgeable. Fail-closed if the file can't be read."""
    if record.name != _INTEGRATION_TOKEN_NAME or (record.scope or "full") != "full":
        return False
    try:
        with open(_raw_path(), encoding="utf-8") as fh:
            raw = fh.read().strip()
    except OSError:
        return False
    return bool(raw) and secrets.compare_digest(hash_token(raw), record.token_hash)


def _user_from_acting_key(raw: str):
    """The user of an MCP caller's key relayed by the sidecar, or None (→ 401).

    Re-verified here rather than trusted: it must be a live key whose scope
    reaches MCP (`mcp` or `full`), and its access class replaces the integration
    token's, so a read-only MCP key stays read-only through the proxy."""
    raw = raw.strip()
    if not raw.startswith(TOKEN_PREFIX):
        return None
    record = (
        db.session.query(ApiToken)
        .filter_by(token_hash=hash_token(raw))
        .first()
    )
    if record is None or (record.scope or "full") not in ("mcp", "full"):
        return None
    # Same expiry rule as a directly-presented key: past expires_at it is no
    # longer a credential, relayed or not.
    if record.expires_at is not None and as_utc(record.expires_at) <= utcnow():
        return None
    g.token_access = record.access or "write"
    # The vault fingerprints the effective credential: this caller's key, not
    # the integration token every MCP caller shares (services/vault.py).
    g.vault_credential = record.token_hash
    return db.session.get(User, record.user_id)


def _read_only_blocked():
    """A read-only API key may only make safe requests. Returns a 403 response for a
    mutating method, else None. No-op for JWT/ingress users (no token → default write)."""
    if getattr(g, "token_access", "write") == "read" and \
            request.method not in ("GET", "HEAD", "OPTIONS"):
        return jsonify({"error": "this API key is read-only",
                        "requestId": request_id_var.get()}), 403
    return None


def enforce_read_only():
    """App-level before_request: a read-only API key may not mutate anything under
    /api/v1, decorated or not — so a new route can't forget the check. The
    decorators keep their own check (belt and braces). Only an Authorization
    header can carry a read-only key, so other requests aren't resolved here."""
    if not request.path.startswith("/api/v1/") or \
            not request.headers.get("Authorization", "").strip():
        return None
    load_current_user()
    return _read_only_blocked()


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
