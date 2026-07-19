import logging
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, current_app

from ..extensions import db, limiter
from ..models import User, Group, GroupInvitation
from ..auth import (
    login_required,
    current_user,
    hash_password,
    verify_password,
    create_token,
)
from ..schemas.serializers import user_out

bp = Blueprint("users", __name__)
_LOGGER = logging.getLogger("homehoard.auth")

# Precomputed hash so a login for a non-existent user still spends the same
# bcrypt time as a real one — removes the user-enumeration timing oracle.
_DUMMY_HASH = hash_password("this-is-not-a-real-password")


def _valid_invitation(token: str):
    """Return the invitation if it exists, is unexpired, and has uses left."""
    inv = db.session.query(GroupInvitation).filter_by(token=token).first()
    if not inv:
        return None
    if inv.uses is not None and inv.uses <= 0:
        return None
    if inv.expires_at:
        try:
            exp = datetime.fromisoformat(str(inv.expires_at).replace("Z", "+00:00"))
        except ValueError:
            exp = None
        if exp is not None:
            now = datetime.now(exp.tzinfo) if exp.tzinfo else datetime.utcnow()
            if now > exp:
                return None
    return inv


def _password_ok(password: str):
    """(valid, error_response) for a candidate password."""
    if len(password or "") < current_app.config["MIN_PASSWORD_LENGTH"]:
        n = current_app.config["MIN_PASSWORD_LENGTH"]
        return False, (jsonify({"error": f"password must be at least {n} characters"}), 422)
    if len(password) > 4096:  # bound bcrypt input work
        return False, (jsonify({"error": "password too long"}), 422)
    return True, None


@bp.post("/users/register")
@limiter.limit("5 per minute")
def register():
    if not current_app.config["ALLOW_REGISTRATION"]:
        return jsonify({"error": "registration disabled"}), 403

    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    name = data.get("name") or ""
    password = data.get("password") or ""
    if not email:
        return jsonify({"error": "email required"}), 422
    ok, err = _password_ok(password)
    if not ok:
        return err
    if db.session.query(User).filter_by(email=email).first():
        return jsonify({"error": "email already registered"}), 409

    token = data.get("token")
    if token:
        invitation = _valid_invitation(token)
        if invitation is None:
            return jsonify({"error": "invalid or expired invitation token"}), 422
        invitation.uses -= 1  # consume one use
        group = invitation.group
        is_owner = False
    else:
        group = Group(name=data.get("groupName") or f"{name}'s Group")
        db.session.add(group)
        db.session.flush()
        is_owner = True

    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        is_owner=is_owner,
        group_id=group.id,
        activated_on=datetime.now(timezone.utc).isoformat(),
    )
    db.session.add(user)
    db.session.commit()
    return jsonify(user_out(user)), 201


@bp.post("/users/login")
@limiter.limit("10 per minute")
def login():
    data = request.get_json(force=True) or {}
    # homebox accepts form or json; support both
    email = (data.get("username") or data.get("email") or
             request.form.get("username") or "").strip().lower()
    password = data.get("password") or request.form.get("password") or ""
    user = db.session.query(User).filter_by(email=email).first()
    # Always run a bcrypt verify (against a dummy hash when the user is missing)
    # so response time doesn't reveal whether the account exists.
    valid = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    if not user or not valid:
        _LOGGER.warning("login failed for %r from %s", email, request.remote_addr)
        return jsonify({"error": "invalid credentials"}), 401
    _LOGGER.info("login ok for %r from %s", email, request.remote_addr)
    token = create_token(user)
    return jsonify(
        {
            "token": f"Bearer {token}",
            "expiresAt": None,
            "attachmentToken": token,
        }
    )


@bp.get("/users/refresh")
@login_required
def refresh():
    token = create_token(current_user())
    return jsonify({"token": f"Bearer {token}", "expiresAt": None})


@bp.post("/users/logout")
@login_required
def logout():
    # Stateless JWT: client discards the token.
    return jsonify({"message": "logged out"})


@bp.get("/users/self")
@login_required
def get_self():
    return jsonify({"item": user_out(current_user())})


@bp.put("/users/self")
@login_required
def update_self():
    data = request.get_json(force=True) or {}
    user = current_user()
    if "name" in data:
        user.name = data["name"]
    if "email" in data:
        new_email = data["email"].strip().lower()
        if new_email != user.email:
            taken = (
                db.session.query(User)
                .filter(User.email == new_email, User.id != user.id)
                .first()
            )
            if taken:
                return jsonify({"error": "email already in use"}), 409
            user.email = new_email
    db.session.commit()
    return jsonify({"item": user_out(user)})


@bp.delete("/users/self")
@login_required
def delete_self():
    db.session.delete(current_user())
    db.session.commit()
    return "", 204


@bp.put("/users/change-password")
@login_required
def change_password():
    data = request.get_json(force=True) or {}
    user = current_user()
    if not verify_password(data.get("current", ""), user.password_hash):
        return jsonify({"error": "current password incorrect"}), 400
    ok, err = _password_ok(data.get("new", ""))
    if not ok:
        return err
    user.password_hash = hash_password(data.get("new", ""))
    db.session.commit()
    return "", 204
