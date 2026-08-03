import os
import uuid

from flask import Blueprint, abort, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from ..auth import current_group, login_required
from ..extensions import db
from ..services import videos
from ..models import Attachment, Bin, Document, Item, MaintenanceEntry
from ..schemas.serializers import attachment_out, bin_out, item_out

bp = Blueprint("attachments", __name__)


def _get_item(item_id) -> Item:
    item = db.session.get(Item, item_id)
    if not item or item.group_id != current_group().id:
        abort(404)
    return item


@bp.post("/items/<item_id>/attachments")
@login_required
def upload(item_id):
    item = _get_item(item_id)
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "file required"}), 422

    atype = request.form.get("type", "attachment")
    name = request.form.get("name") or file.filename
    stored = f"{uuid.uuid4()}-{secure_filename(file.filename)}"
    path = os.path.join(current_app.config["attachments_dir"](), stored)
    file.save(path)

    doc = Document(title=name, path=path, group_id=current_group().id)
    db.session.add(doc)
    db.session.flush()

    is_primary = atype == "photo" and not any(
        a.primary for a in item.attachments
    )
    att = Attachment(type=atype, primary=is_primary, item_id=item.id,
                     document_id=doc.id)
    db.session.add(att)
    db.session.commit()
    return jsonify(item_out(item)), 201


@bp.get("/items/<item_id>/attachments/<attachment_id>")
@login_required
def download(item_id, attachment_id):
    _get_item(item_id)
    att = db.session.get(Attachment, attachment_id)
    if not att or att.item_id != item_id:
        abort(404)
    return send_file(att.document.path, download_name=att.document.title,
                     as_attachment=True)


@bp.put("/items/<item_id>/attachments/<attachment_id>")
@login_required
def update(item_id, attachment_id):
    item = _get_item(item_id)
    att = db.session.get(Attachment, attachment_id)
    if not att or att.item_id != item_id:
        abort(404)
    data = request.get_json(force=True) or {}
    if "type" in data:
        att.type = data["type"]
    if "title" in data and att.document:
        att.document.title = data["title"]
    if data.get("primary"):
        for other in item.attachments:
            other.primary = other.id == att.id
    db.session.commit()
    return jsonify(item_out(item))


@bp.delete("/items/<item_id>/attachments/<attachment_id>")
@login_required
def delete(item_id, attachment_id):
    _get_item(item_id)
    att = db.session.get(Attachment, attachment_id)
    if not att or att.item_id != item_id:
        abort(404)
    if att.document and os.path.exists(att.document.path):
        try:
            os.remove(att.document.path)
        except OSError:
            # Best-effort: the DB row is the source of truth. A missing/locked
            # file must not block deleting the attachment record.
            pass
    db.session.delete(att)
    db.session.commit()
    return "", 204


# ---------------------------------------------------------------------------
# Bin attachments — same behavior as item attachments.
# ---------------------------------------------------------------------------
def _get_bin(bin_id) -> Bin:
    b = db.session.get(Bin, bin_id)
    if not b or b.group_id != current_group().id:
        abort(404)
    return b


@bp.post("/bins/<bin_id>/attachments")
@login_required
def bin_upload(bin_id):
    b = _get_bin(bin_id)
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "file required"}), 422

    atype = request.form.get("type", "attachment")
    name = request.form.get("name") or file.filename
    stored = f"{uuid.uuid4()}-{secure_filename(file.filename)}"
    path = os.path.join(current_app.config["attachments_dir"](), stored)
    file.save(path)

    doc = Document(title=name, path=path, group_id=current_group().id)
    db.session.add(doc)
    db.session.flush()

    is_primary = atype == "photo" and not any(a.primary for a in b.attachments)
    att = Attachment(type=atype, primary=is_primary, bin_id=b.id,
                     document_id=doc.id)
    db.session.add(att)
    db.session.commit()
    return jsonify(bin_out(b)), 201


@bp.get("/bins/<bin_id>/attachments/<attachment_id>")
@login_required
def bin_download(bin_id, attachment_id):
    _get_bin(bin_id)
    att = db.session.get(Attachment, attachment_id)
    if not att or att.bin_id != bin_id:
        abort(404)
    return send_file(att.document.path, download_name=att.document.title,
                     as_attachment=True)


@bp.put("/bins/<bin_id>/attachments/<attachment_id>")
@login_required
def bin_update(bin_id, attachment_id):
    b = _get_bin(bin_id)
    att = db.session.get(Attachment, attachment_id)
    if not att or att.bin_id != bin_id:
        abort(404)
    data = request.get_json(force=True) or {}
    if "type" in data:
        att.type = data["type"]
    if "title" in data and att.document:
        att.document.title = data["title"]
    if data.get("primary"):
        for other in b.attachments:
            other.primary = other.id == att.id
    db.session.commit()
    return jsonify(bin_out(b))


@bp.delete("/bins/<bin_id>/attachments/<attachment_id>")
@login_required
def bin_delete(bin_id, attachment_id):
    _get_bin(bin_id)
    att = db.session.get(Attachment, attachment_id)
    if not att or att.bin_id != bin_id:
        abort(404)
    if att.document and os.path.exists(att.document.path):
        try:
            os.remove(att.document.path)
        except OSError:
            # Best-effort: the DB row is the source of truth. A missing/locked
            # file must not block deleting the attachment record.
            pass
    db.session.delete(att)
    db.session.commit()
    return "", 204


# Standalone document download endpoint referenced by serialized attachments.
@bp.get("/documents/<document_id>")
@login_required
def get_document(document_id):
    doc = db.session.get(Document, document_id)
    if not doc or doc.group_id != current_group().id:
        abort(404)
    return send_file(doc.path, download_name=doc.title, as_attachment=True)


# ---------------------------------------------------------------------------
# How-to videos.
#
# A video is EITHER a link (YouTube/Vimeo embed inline, anything else opens in
# a new tab) or an uploaded file. It hangs off an item ("how this thing works")
# or a maintenance entry ("how to do this job"), so the right clip is present
# when a task comes due.
# ---------------------------------------------------------------------------

def _video_from_request(parent_kwargs: dict):
    """Build an unsaved Attachment from a link or an upload. Raises VideoError.

    The file is NOT written here — only once the row has passed validation, so a
    rejected request never leaves an orphan on disk.
    """
    upload = request.files.get("file")
    title = (request.form.get("title") if upload
             else (request.get_json(silent=True) or {}).get("title")) or ""
    att = Attachment(type="video", **parent_kwargs)
    pending = None

    if upload:
        mime = videos.video_mime(upload.filename or "")
        if not mime:
            raise videos.VideoError(
                "that file is not a video we can play "
                f"({', '.join(sorted(videos.VIDEO_MIME_BY_EXT))})")
        stored = f"{uuid.uuid4()}-{secure_filename(upload.filename)}"
        path = os.path.join(current_app.config["attachments_dir"](), stored)
        doc = Document(title=upload.filename or "video", path=path,
                       group_id=current_group().id)
        db.session.add(doc)
        db.session.flush()
        att.document_id = doc.id
        att.title = str(title)[:255].strip() or (upload.filename or "Video")
        pending = (upload, path)
    else:
        att.url = videos.normalize_url((request.get_json(silent=True) or {}).get("url", ""))
        att.title = str(title)[:255].strip() or "Video"

    videos.validate(att)
    return att, pending


def _create_video(parent_kwargs: dict):
    try:
        att, pending = _video_from_request(parent_kwargs)
    except videos.VideoError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 422
    if pending:
        upload, path = pending
        upload.save(path)
    db.session.add(att)
    db.session.commit()
    return jsonify(attachment_out(att)), 201


@bp.post("/items/<item_id>/videos")
@login_required
def add_item_video(item_id):
    item = _get_item(item_id)
    return _create_video({"item_id": item.id})


@bp.post("/items/<item_id>/maintenance/<entry_id>/videos")
@login_required
def add_maintenance_video(item_id, entry_id):
    item = _get_item(item_id)
    entry = db.session.get(MaintenanceEntry, entry_id)
    # Checked against the item we already tenant-scoped, so an entry id from
    # another household 404s rather than accepting a video.
    if not entry or entry.item_id != item.id:
        abort(404)
    return _create_video({"maintenance_entry_id": entry.id})


def _get_video(attachment_id: str) -> Attachment:
    att = db.session.get(Attachment, attachment_id)
    if not att or att.type != "video":
        abort(404)
    # Tenancy: reach the owning item either directly or through the maintenance
    # entry, and check the group. Never trust the id alone.
    item = att.item or (att.maintenance_entry.item if att.maintenance_entry else None)
    if item is None or item.group_id != current_group().id:
        abort(404)
    return att


@bp.get("/videos/<attachment_id>/stream")
@login_required
def stream_video(attachment_id):
    """Serve an uploaded video for inline playback.

    conditional=True (send_file's default) answers Range requests, which is what
    lets the player seek. The Content-Type comes from our own extension
    allowlist, never from the uploaded filename — that is what stops a file
    called "clip.mp4" full of HTML executing in the app's origin.
    """
    att = _get_video(attachment_id)
    if not att.document:
        abort(404)  # a link has nothing to stream
    mime = videos.video_mime(att.document.title) or videos.video_mime(att.document.path)
    if not mime or not os.path.isfile(att.document.path):
        abort(404)
    return send_file(att.document.path, mimetype=mime, conditional=True)


@bp.delete("/videos/<attachment_id>")
@login_required
def delete_video(attachment_id):
    att = _get_video(attachment_id)
    if att.document and att.document.path and os.path.exists(att.document.path):
        try:
            os.remove(att.document.path)
        except OSError:
            # Best-effort, matching the other attachment paths: the row is the
            # source of truth and a missing file must not block the delete.
            pass
    db.session.delete(att)
    db.session.commit()
    return "", 204
