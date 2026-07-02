"""Authentication layer.

Supports two modes:

* **Enabled** (default): JWT bearer tokens issued at login. Requests must send
  ``Authorization: Bearer <token>``.
* **Disabled** (``HBOX_DISABLE_AUTH=true``): every request is transparently
  bound to a default user/group. This is intended for running behind Home
  Assistant ingress, which already authenticates the user.
"""
import functools
from datetime import datetime, timezone

import jwt
from flask import current_app, g, request, jsonify
from passlib.hash import bcrypt

from .extensions import db
from .models import User, Group

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
    exp = datetime.now(timezone.utc) + current_app.config["JWT_EXPIRES"]
    payload = {"sub": user.id, "exp": exp}
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
    group = Group(name=DEFAULT_GROUP, currency="usd")
    db.session.add(group)
    db.session.flush()
    user = User(
        name="Local User",
        email=DEFAULT_EMAIL,
        password_hash=hash_password("unused"),
        is_owner=True,
        group_id=group.id,
    )
    db.session.add(user)
    db.session.commit()
    return user


def load_current_user():
    """Resolve the current user, honoring the DISABLE_AUTH toggle."""
    if current_app.config["DISABLE_AUTH"]:
        return _default_user()

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[len("Bearer "):].strip()
    user_id = decode_token(token)
    if not user_id:
        return None
    return db.session.get(User, user_id)


def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = load_current_user()
        if user is None:
            return jsonify({"error": "unauthorized"}), 401
        g.current_user = user
        g.current_group = user.group
        return fn(*args, **kwargs)

    return wrapper


def current_user() -> User:
    return g.current_user


def current_group() -> Group:
    return g.current_group
