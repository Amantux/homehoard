from flask import Blueprint, request, jsonify, abort

from ..extensions import db
from ..models import Notifier
from ..auth import login_required, current_group, current_user
from ..schemas.serializers import notifier_out

bp = Blueprint("notifiers", __name__)


def _get(notifier_id):
    n = db.session.get(Notifier, notifier_id)
    if not n or n.group_id != current_group().id:
        abort(404)
    return n


@bp.get("/notifiers")
@login_required
def list_notifiers():
    notifiers = (
        db.session.query(Notifier).filter_by(user_id=current_user().id).all()
    )
    return jsonify([notifier_out(n) for n in notifiers])


@bp.post("/notifiers")
@login_required
def create_notifier():
    data = request.get_json(force=True) or {}
    n = Notifier(
        name=data.get("name", ""),
        url=data.get("url", ""),
        is_active=data.get("isActive", True),
        group_id=current_group().id,
        user_id=current_user().id,
    )
    db.session.add(n)
    db.session.commit()
    return jsonify(notifier_out(n)), 201


@bp.put("/notifiers/<notifier_id>")
@login_required
def update_notifier(notifier_id):
    n = _get(notifier_id)
    data = request.get_json(force=True) or {}
    if "name" in data:
        n.name = data["name"]
    if "url" in data:
        n.url = data["url"]
    if "isActive" in data:
        n.is_active = data["isActive"]
    db.session.commit()
    return jsonify(notifier_out(n))


@bp.delete("/notifiers/<notifier_id>")
@login_required
def delete_notifier(notifier_id):
    db.session.delete(_get(notifier_id))
    db.session.commit()
    return "", 204


@bp.post("/notifiers/test")
@login_required
def test_notifier():
    """Best-effort test using Apprise if available, else validate the URL."""
    data = request.get_json(force=True) or {}
    url = data.get("url", "")
    if not url:
        return jsonify({"error": "url required"}), 422
    try:
        import apprise  # optional dependency

        ap = apprise.Apprise()
        ok = ap.add(url) and ap.notify(
            body="HomeHoard test notification", title="HomeHoard"
        )
        return ("", 204) if ok else (jsonify({"error": "notify failed"}), 400)
    except ImportError:
        # Apprise not installed; accept syntactically plausible URLs.
        if "://" in url:
            return "", 204
        return jsonify({"error": "invalid url"}), 400
