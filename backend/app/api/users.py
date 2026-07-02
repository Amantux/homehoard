from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, g

from ..extensions import db
from ..models import User, Group
from ..auth import (
    login_required,
    current_user,
    hash_password,
    verify_password,
    create_token,
)
from ..schemas.serializers import user_out

bp = Blueprint("users", __name__)


@bp.post("/users/register")
def register():
    from flask import current_app

    if not current_app.config["ALLOW_REGISTRATION"]:
        return jsonify({"error": "registration disabled"}), 403

    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    name = data.get("name") or ""
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "email and password required"}), 422
    if db.session.query(User).filter_by(email=email).first():
        return jsonify({"error": "email already registered"}), 409

    token = data.get("token")
    if token:
        group = db.session.query(Group).join(Group.invitations).filter_by(
            token=token
        ).first()
        if not group:
            return jsonify({"error": "invalid invitation token"}), 422
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
def login():
    data = request.get_json(force=True) or {}
    # homebox accepts form or json; support both
    email = (data.get("username") or data.get("email") or
             request.form.get("username") or "").strip().lower()
    password = data.get("password") or request.form.get("password") or ""
    user = db.session.query(User).filter_by(email=email).first()
    if not user or not verify_password(password, user.password_hash):
        return jsonify({"error": "invalid credentials"}), 401
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
        user.email = data["email"].strip().lower()
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
    user.password_hash = hash_password(data.get("new", ""))
    db.session.commit()
    return "", 204
