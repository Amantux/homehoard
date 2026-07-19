import ipaddress
import socket
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify, abort

from ..extensions import db
from ..models import Notifier
from ..auth import login_required, current_group, current_user
from ..schemas.serializers import notifier_out

bp = Blueprint("notifiers", __name__)

# Schemes that carry an arbitrary network host (SSRF-relevant). Provider schemes
# like discord://, tgram://, slack:// target fixed provider endpoints and are
# left alone.
_HOST_SCHEMES = {"http", "https", "json", "jsons", "xml", "xmls", "form", "forms"}


def _url_is_safe(url: str) -> bool:
    """Reject notifier URLs that would let the server reach internal hosts
    (SSRF: cloud metadata, RFC1918, loopback, link-local, …)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if not parsed.scheme:
        return False
    if parsed.scheme.lower() not in _HOST_SCHEMES:
        return True  # provider scheme → fixed endpoint, not attacker-chosen
    host = parsed.hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False  # unresolvable → refuse rather than let apprise try
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def _get(notifier_id):
    # Notifiers are per-user; scope by both user and group so a group peer can't
    # read/modify another member's notifier (which may hold a webhook secret).
    n = db.session.get(Notifier, notifier_id)
    if not n or n.group_id != current_group().id or n.user_id != current_user().id:
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
    url = data.get("url", "")
    if url and not _url_is_safe(url):
        return jsonify({"error": "notifier URL is not allowed"}), 422
    n = Notifier(
        name=data.get("name", ""),
        url=url,
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
        if data["url"] and not _url_is_safe(data["url"]):
            return jsonify({"error": "notifier URL is not allowed"}), 422
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
    if not _url_is_safe(url):
        return jsonify({"error": "notifier URL is not allowed"}), 422
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
