"""Vault mode: hidden items are invisible until this session is unlocked.

Two rules hold the feature together, and both exist because the failure is
SILENT — a hidden item that quietly shows up looks exactly like a working app.

1. **One chokepoint.** There are ~22 `query(Item)` sites across a dozen files.
   Every user-facing read goes through `visible()`; nothing filters `hidden` by
   hand. A read path that forgets is the whole feature failing, so the leak test
   enumerates surfaces rather than trusting review.

2. **Unlock is per CREDENTIAL, not per user or per household.** The presented
   Authorization value is fingerprinted (sha256, via the same `hash_token` used
   for API tokens), so unlocking in chat does not unlock another device, another
   member, or a machine token.

What this is NOT: encryption. Hidden rows sit in the database in plaintext, so
anyone with the DB file, a filesystem backup, or an admin token reads them
regardless of lock state. This gates the *application's* surfaces — browsing,
searching, the agent — not the box.
"""
import logging
from datetime import timedelta

from flask import g, has_request_context, request
from passlib.hash import bcrypt

from ..extensions import db
from ..models import Group, Item, VaultUnlock, hash_token, utcnow

_LOGGER = logging.getLogger("homehoard.vault")


def _now():
    """Naive UTC. `models.utcnow()` is timezone-AWARE, but the DateTime columns
    are naive, so a value read back from SQLite cannot be compared against it
    ("can't compare offset-naive and offset-aware datetimes"). The rest of the
    app compares in naive UTC for the same reason."""
    return utcnow().replace(tzinfo=None)

# An unlock you forget about is how this ends up permanently open. Long enough
# to be invisible in normal use, short enough that an abandoned session closes.
UNLOCK_TTL = timedelta(hours=12)

# bcrypt silently truncates past 72 bytes; bound the work like users.py does.
_MAX_PHRASE = 1024


def _credential():
    """The raw Authorization credential for this request, or None.

    Read from the header rather than any parsed identity: two logins by the same
    user are two sessions, which is exactly the granularity we promised."""
    if not has_request_context():
        return None
    raw = request.headers.get("Authorization") or ""
    raw = raw[7:] if raw.lower().startswith("bearer ") else raw
    return raw.strip() or None


def _fingerprint():
    raw = _credential()
    return hash_token(raw) if raw else None


def configured(group) -> bool:
    """True when this household has a vault passphrase set."""
    return bool((group.vault_passphrase_hash or "").strip())


def set_passphrase(group, phrase: str) -> None:
    """Store the phrase as a bcrypt hash. The phrase itself is never persisted."""
    group.vault_passphrase_hash = bcrypt.hash(phrase[:_MAX_PHRASE])


def check_passphrase(group, phrase: str) -> bool:
    stored = (group.vault_passphrase_hash or "").strip()
    if not stored:
        return False
    try:
        return bcrypt.verify((phrase or "")[:_MAX_PHRASE], stored)
    except ValueError:
        return False


def unlock(group, user, phrase: str) -> bool:
    """Verify and open THIS session. Returns False without changing anything on
    a wrong phrase; the attempted value is never logged."""
    if not check_passphrase(group, phrase):
        _LOGGER.info("vault unlock refused for group %s", group.id)
        return False
    fp = _fingerprint()
    if not fp:
        return False
    lock(group)  # replace any existing row for this credential
    db.session.add(VaultUnlock(
        group_id=group.id, user_id=getattr(user, "id", None),
        credential_fingerprint=fp, expires_at=_now() + UNLOCK_TTL))
    db.session.commit()
    g.__dict__.pop("_vault_unlocked", None)
    return True


def lock(group) -> int:
    """Close this session's unlock. Returns how many rows were cleared."""
    fp = _fingerprint()
    if not fp:
        return 0
    n = (db.session.query(VaultUnlock)
         .filter_by(group_id=group.id, credential_fingerprint=fp)
         .delete(synchronize_session=False))
    db.session.commit()
    g.__dict__.pop("_vault_unlocked", None)
    return n


def lock_all_for_user(user_id) -> int:
    """Close every unlock held by a user — called on logout, so a shared machine
    doesn't leave the vault open for the next person."""
    n = (db.session.query(VaultUnlock).filter_by(user_id=user_id)
         .delete(synchronize_session=False))
    db.session.commit()
    return n


def is_unlocked(group=None) -> bool:
    """Is THIS request's credential currently unlocked? Cached per request: it is
    consulted by nearly every query and must not cost a round-trip each time."""
    if has_request_context() and "_vault_unlocked" in g.__dict__:
        return g.__dict__["_vault_unlocked"]
    result = False
    fp = _fingerprint()
    if fp:
        q = db.session.query(VaultUnlock).filter_by(credential_fingerprint=fp)
        if group is not None:
            q = q.filter_by(group_id=group.id)
        row = q.first()
        if row is not None:
            if row.expires_at and row.expires_at < _now():
                # Expired: clear it so `status` reports the truth.
                db.session.delete(row)
                db.session.commit()
            else:
                result = True
    if has_request_context():
        g.__dict__["_vault_unlocked"] = result
    return result


def visible(query, *, include_hidden=None):
    """EVERY user-facing read of items goes through here.

    Excludes hidden rows unless this session is unlocked. `include_hidden=True`
    is for the two paths that MUST see them while locked — unhide-by-name and
    list-hidden — because a hidden item you cannot resolve is a hidden item you
    can never get back.

    Deliberately NOT applied to the `misc.py` maintenance routines
    (ensure_asset_ids, zero_time_fields, set_primary_photos): they repair data
    across every row and surface nothing to a user.
    """
    if include_hidden is True:
        return query
    if include_hidden is None and is_unlocked():
        return query
    return query.filter(Item.hidden.is_(False))


def readable(item) -> bool:
    """May this item be surfaced to the caller right now?

    For the by-ID fetches. A list endpoint filters with `visible()`, but
    `db.session.get(Item, id)` walks straight past it — and knowing an id is not
    authorisation: ids travel in old exports, QR tags and shared links. Callers
    abort 404, never 403: "this exists but is hidden" is itself the leak."""
    return item is not None and (not item.hidden or is_unlocked())


def hidden_count(gid) -> int:
    """How many items are hidden — safe to report while locked (a count, not
    the contents), so the UI can show that a vault exists at all."""
    return (db.session.query(Item)
            .filter(Item.group_id == gid, Item.hidden.is_(True)).count())


def status(group) -> dict:
    return {
        "configured": configured(group),
        "locked": not is_unlocked(group),
        "hiddenCount": hidden_count(group.id),
    }


def group_for(gid):
    return db.session.get(Group, gid)
