from flask import Blueprint, request, jsonify, abort

from ..extensions import db
from ..models import Notifier
from ..auth import login_required, current_group, current_user
from ..schemas.serializers import notifier_out
# The SSRF guard lives in the service so the API and the dispatcher share one
# definition and both validate at the point of use.
from ..services.notify import url_is_safe as _url_is_safe

bp = Blueprint("notifiers", __name__)


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


@bp.post("/notifiers/dispatch")
@login_required
def dispatch_alerts():
    """Send the current alert digest (overdue lends, warranties expiring soon,
    overdue maintenance) to the group's active notifiers.

    The add-on has no scheduler, so this is meant to be called by a Home
    Assistant automation on a schedule (e.g. daily). By default it sends nothing
    when there are no alerts — pass ?force=1 to always send (useful for a "test
    the pipeline" automation). Household-wide: any member's active notifier
    fires, so a shared install notifies everyone who opted in."""
    from ..services.alerts import alert_digest
    from ..services.notify import send_to_notifiers

    gid = current_group().id
    digest = alert_digest(gid)
    force = (request.args.get("force") or "").lower() in ("1", "true", "yes")
    if digest["isEmpty"] and not force:
        return jsonify({"sent": 0, "skipped": "no alerts", "digest": digest})

    notifiers = (db.session.query(Notifier)
                 .filter_by(group_id=gid, is_active=True).all())
    results = send_to_notifiers(notifiers, title="HomeHoard alerts",
                                body=digest["text"])
    return jsonify({"sent": sum(1 for r in results if r["ok"]),
                    "attempted": len(results), "results": results,
                    "digest": digest})


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
