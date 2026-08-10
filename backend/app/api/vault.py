"""Vault endpoints: set a passphrase, unlock this session, lock it again.

The REST API is the only implementation — the MCP tools and the chat handlers
are thin wrappers over these, so the three surfaces cannot drift on what
"unlocked" means.
"""
from flask import Blueprint, jsonify, request

from ..auth import current_group, current_user, login_required, owner_required
from ..models import Item
import logging

from ..extensions import db, limiter
from ..services import vault

bp = Blueprint("vault", __name__)

_LOGGER = logging.getLogger("homehoard.vault")

# bcrypt already bounds the work, but an unbounded body is still pointless work.
_MAX_PHRASE = 1024


@bp.get("/vault/status")
@login_required
def status():
    """Whether a vault exists and whether THIS session is open.

    Reports a COUNT, never the contents: the UI needs to show that a vault
    exists (otherwise a user cannot discover the feature) without that being a
    way to read what is in it."""
    return jsonify(vault.status(current_group()))


@bp.post("/vault/passphrase")
@limiter.limit("10/hour")
@owner_required
def set_passphrase():
    """Set or change the household passphrase. Owner-only: it gates every
    member's view, so it is household config, not a personal preference.

    Changing an existing phrase requires the current one — otherwise anyone
    with an open session could silently re-key the vault and lock the owner out.
    """
    data = request.get_json(silent=True) or {}
    phrase = (data.get("phrase") or "").strip()
    if not phrase:
        return jsonify({"error": "phrase required"}), 422
    if len(phrase) > _MAX_PHRASE:
        return jsonify({"error": "phrase is too long"}), 422

    group = current_group()
    if vault.configured(group):
        current = (data.get("currentPhrase") or "").strip()
        if not vault.check_passphrase(group, current):
            return jsonify({"error": "current passphrase is incorrect"}), 401

    vault.set_passphrase(group, phrase)
    db.session.commit()
    return jsonify(vault.status(group))


@bp.post("/vault/unlock")
# Rate-limited because this is a guessable secret: without it the endpoint is an
# offline-speed oracle over HTTP.
@limiter.limit("10/minute;60/hour")
@login_required
def unlock():
    data = request.get_json(silent=True) or {}
    phrase = (data.get("phrase") or "")[:_MAX_PHRASE]
    group = current_group()
    if not vault.configured(group):
        return jsonify({"error": "no vault passphrase is set"}), 409
    if not vault.unlock(group, current_user(), phrase):
        # Deliberately the same message whatever went wrong, and the attempted
        # value is never echoed or logged.
        return jsonify({"error": "incorrect passphrase"}), 401
    return jsonify(vault.status(group))


@bp.post("/vault/lock")
@login_required
def lock():
    group = current_group()
    vault.lock(group)
    return jsonify(vault.status(group))


@bp.post("/vault/reset")
# Destructive and owner-gated, but still rate-limited: a reset is also a way to
# repeatedly probe how much is hidden.
@limiter.limit("5/hour")
@owner_required
def reset():
    """Forgot the passphrase: reset the vault, at the price of its contents.

    Two-step, like every destructive operation here — the first call previews
    and changes nothing, only ``{"confirm": true}`` acts.

    The preview reports a COUNT and never the names. The house rule is that a
    destructive preview must name exactly what is lost, and this is the one
    place that rule inverts: naming them would hand the vault's contents to
    someone who has just demonstrated they cannot open it.

    Wiping is deliberate, not a shortcut. If a reset merely re-keyed the vault,
    any owner could re-key their way into reading it, and the passphrase would
    protect nothing from the people most likely to be looking. So the reset
    returns the vault, never its contents.
    """
    group = current_group()
    hidden = (db.session.query(Item)
              .filter(Item.group_id == group.id, Item.hidden.is_(True)))
    count = hidden.count()

    if not (request.get_json(silent=True) or {}).get("confirm"):
        return jsonify({
            "willDestroy": count,
            "confirmed": False,
            "warning": ("This permanently deletes the hidden items. They cannot "
                        "be recovered, and their names are not shown here."),
        })

    for item in hidden.all():
        db.session.delete(item)          # cascades holdings/attachments/fields
    vault.clear(group)                   # drop the phrase AND every open unlock
    db.session.commit()
    _LOGGER.info("vault reset for group %s: %s item(s) destroyed", group.id, count)
    return jsonify({"destroyed": count, "confirmed": True,
                    **vault.status(group)})
