"""Multiple QR codes per item, bin, or location.

Each :class:`QrTag` has a short unique token. The QR image encodes a scan URL
(``<app>/#/t/<token>``) that the SPA resolves and redirects to the target.

URL building is Home Assistant ingress aware: HA sets the ``X-Ingress-Path``
header with the add-on's base path, which we honor so printed codes work when
the app is reached through ingress.
"""
import io

from flask import Blueprint, request, jsonify, abort, send_file

from ..extensions import db
from ..models import QrTag, Item, Bin, Location, KINDS, gen_token
from ..auth import login_required, current_group
from ..schemas.serializers import qrtag_out

bp = Blueprint("qrtags", __name__)


def _base_url() -> str:
    """Best-effort external base URL, honoring proxy / ingress headers."""
    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    forwarded_host = request.headers.get("X-Forwarded-Host")
    scheme = forwarded_proto or request.scheme
    host = forwarded_host or request.host
    # Home Assistant ingress base path (e.g. /api/hassio_ingress/<token>).
    ingress = request.headers.get("X-Ingress-Path", "").rstrip("/")
    return f"{scheme}://{host}{ingress}"


def scan_url(token: str) -> str:
    return f"{_base_url()}/#/t/{token}"


def _target_or_404(kind: str, target_id: str):
    model = {"item": Item, "bin": Bin, "location": Location}[kind]
    obj = db.session.get(model, target_id)
    if not obj or obj.group_id != current_group().id:
        abort(404, description="target not found")
    return obj


def _get_tag(tag_id) -> QrTag:
    tag = db.session.get(QrTag, tag_id)
    if not tag or tag.group_id != current_group().id:
        abort(404)
    return tag


@bp.get("/qr-tags")
@login_required
def list_tags():
    q = db.session.query(QrTag).filter_by(group_id=current_group().id)
    kind = request.args.get("kind")
    target_id = request.args.get("targetId")
    if kind and target_id:
        col = {"item": QrTag.item_id, "bin": QrTag.bin_id,
               "location": QrTag.location_id}.get(kind)
        if col is None:
            return jsonify({"error": "invalid kind"}), 422
        q = q.filter(QrTag.kind == kind, col == target_id)
    return jsonify([qrtag_out(t, scan_url(t.token)) for t in q.all()])


@bp.post("/qr-tags")
@login_required
def create_tag():
    data = request.get_json(force=True) or {}
    kind = data.get("kind")
    target_id = data.get("targetId")
    if kind not in KINDS or not target_id:
        return jsonify({"error": "kind (item|bin|location) and targetId required"}), 422
    _target_or_404(kind, target_id)

    source = data.get("source", "generated")
    tag = QrTag(
        kind=kind,
        description=data.get("description", ""),
        group_id=current_group().id,
        source=source,
    )
    setattr(tag, f"{kind}_id", target_id)

    if source == "external":
        # Register the user's own QR/barcode value.
        value = (data.get("code") or "").strip()
        if not value:
            return jsonify({"error": "code is required for external tags"}), 422
        existing = (
            db.session.query(QrTag)
            .filter_by(group_id=current_group().id, code=value)
            .first()
        )
        if existing:
            return jsonify({
                "error": "that code is already assigned",
                "tag": qrtag_out(existing, scan_url(existing.token)),
            }), 409
        tag.code = value
        tag.token = value if len(value) <= 60 else gen_token()
        tag.code_format = data.get("codeFormat", "barcode")
    else:
        # Shelfie-generated QR: token doubles as the code.
        tag.code = tag.token
        tag.code_format = "qr"

    db.session.add(tag)
    db.session.commit()
    return jsonify(qrtag_out(tag, scan_url(tag.token))), 201


@bp.get("/qr-tags/<tag_id>")
@login_required
def get_tag(tag_id):
    tag = _get_tag(tag_id)
    return jsonify(qrtag_out(tag, scan_url(tag.token)))


@bp.delete("/qr-tags/<tag_id>")
@login_required
def delete_tag(tag_id):
    db.session.delete(_get_tag(tag_id))
    db.session.commit()
    return "", 204


@bp.get("/qr-tags/<tag_id>/image")
@login_required
def tag_image(tag_id):
    import qrcode

    tag = _get_tag(tag_id)
    img = qrcode.make(scan_url(tag.token))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png",
                     download_name=f"qr-{tag.token}.png")


@bp.get("/qr-tags/resolve/<path:value>")
@login_required
def resolve(value):
    """Resolve a scanned value to its target so the SPA can navigate to it.

    Matches either a Shelfie-generated token or a user-registered external
    code (barcode / own QR payload). If the scanned value is a full Shelfie
    scan URL, the caller should pass just the token portion.
    """
    gid = current_group().id
    tag = (
        db.session.query(QrTag)
        .filter(QrTag.group_id == gid,
                db.or_(QrTag.token == value, QrTag.code == value))
        .first()
    )
    if not tag:
        return jsonify({"error": "not found", "code": value}), 404
    return jsonify(qrtag_out(tag, scan_url(tag.token)))
