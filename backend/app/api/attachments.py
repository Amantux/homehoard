import os
import uuid

from flask import Blueprint, request, jsonify, abort, send_file, current_app
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import Item, Attachment, Document
from ..auth import login_required, current_group
from ..schemas.serializers import item_out, attachment_out

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
    return send_file(att.document.path, download_name=att.document.title)


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
    return send_file(doc.path, download_name=doc.title)
