"""Vault endpoints: set a passphrase, unlock this session, lock it again.

The REST API is the only implementation — the MCP tools and the chat handlers
are thin wrappers over these, so the three surfaces cannot drift on what
"unlocked" means.
"""
from flask import Blueprint, jsonify, request

from ..auth import current_group, current_user, login_required, owner_required
from ..extensions import db, limiter
from ..services import vault

bp = Blueprint("vault", __name__)

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
