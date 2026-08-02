"""Manage long-lived API tokens (API keys) for machine clients.

The raw token is returned exactly once, on creation. After that only its name,
hint, and usage timestamp are visible. Tokens are group-scoped like the rest of
the API. Primarily used to connect the Home Assistant integration when app auth
is enabled (the add-on runs auth-disabled and needs none).
"""
from flask import Blueprint, request, jsonify, abort

from ..extensions import db
from ..models import ApiToken, TOKEN_SCOPES, TOKEN_ACCESS, generate_raw_token, hash_token
from ..auth import owner_required, current_user, current_group
from ..schemas.serializers import iso

bp = Blueprint("tokens", __name__)


def _out(t: ApiToken) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "hint": t.hint,
        "scope": t.scope or "full",
        "access": t.access or "write",
        "createdAt": iso(t.created_at),
        "lastUsedAt": iso(t.last_used_at),
    }


@bp.get("/tokens")
@owner_required
def list_tokens():
    tokens = (
        db.session.query(ApiToken)
        .filter_by(group_id=current_group().id)
        .order_by(ApiToken.created_at.desc())
        .all()
    )
    return jsonify([_out(t) for t in tokens])


@bp.post("/tokens")
@owner_required
def create_token_endpoint():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip() or "API token"
    scope = (data.get("scope") or "full").strip().lower()
    if scope not in TOKEN_SCOPES:
        return jsonify({"error": f"scope must be one of {', '.join(TOKEN_SCOPES)}"}), 400
    if scope == "debug":
        # owner_required only proves ownership of the caller's OWN group, and a
        # debug key reads the whole INSTANCE's logs — every household's request
        # paths, item names and (masked but identifiable) sign-in addresses.
        # Restrict minting one to the founding household's owner, the same bar
        # the shared AI-provider config uses.
        from .misc import _instance_admin_or_403
        denied = _instance_admin_or_403()
        if denied:
            return denied
    access = (data.get("access") or "write").strip().lower()
    if access not in TOKEN_ACCESS:
        return jsonify({"error": f"access must be one of {', '.join(TOKEN_ACCESS)}"}), 400
    raw = generate_raw_token()
    token = ApiToken(
        name=name,
        scope=scope,
        access=access,
        token_hash=hash_token(raw),
        hint=raw[:7],  # "hh_" + first 4 chars
        user_id=current_user().id,
        group_id=current_group().id,
    )
    db.session.add(token)
    db.session.commit()
    # `token` (the raw value) is included ONLY in this create response.
    return jsonify({**_out(token), "token": raw}), 201


@bp.delete("/tokens/<token_id>")
@owner_required
def revoke_token(token_id):
    token = db.session.get(ApiToken, token_id)
    if not token or token.group_id != current_group().id:
        abort(404)
    db.session.delete(token)
    db.session.commit()
    return "", 204
