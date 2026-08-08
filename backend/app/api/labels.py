from flask import Blueprint, request, jsonify, abort

from ..extensions import db
from ..models import Label
from ..auth import login_required, current_group
from ..schemas.serializers import label_out, label_summary

bp = Blueprint("labels", __name__)


def _get(label_id):
    label = db.session.get(Label, label_id)
    if not label or label.group_id != current_group().id:
        abort(404)
    return label


@bp.get("/labels")
@login_required
def list_labels():
    labels = db.session.query(Label).filter_by(group_id=current_group().id).all()
    return jsonify([label_summary(lbl) for lbl in labels])


def _owned_parent(parent_id):
    """A Label parentId in this group, or 404 — no cross-group nesting."""
    if not parent_id:
        return None
    row = db.session.get(Label, parent_id)
    if row is None or row.group_id != current_group().id:
        abort(404)
    return parent_id


@bp.post("/labels")
@login_required
def create_label():
    data = request.get_json(force=True) or {}
    label = Label(
        name=data.get("name", ""),
        description=data.get("description", ""),
        color=data.get("color", ""),
        icon=data.get("icon", ""),
        parent_id=_owned_parent(data.get("parentId")),
        group_id=current_group().id,
    )
    db.session.add(label)
    db.session.commit()
    return jsonify(label_out(label)), 201


@bp.get("/labels/<label_id>")
@login_required
def get_label(label_id):
    return jsonify(label_out(_get(label_id)))


@bp.put("/labels/<label_id>")
@login_required
def update_label(label_id):
    label = _get(label_id)
    data = request.get_json(force=True) or {}
    for field in ("name", "description", "color", "icon"):
        if field in data:
            setattr(label, field, data[field])
    if "parentId" in data:
        label.parent_id = _owned_parent(data["parentId"])
    db.session.commit()
    return jsonify(label_out(label))


@bp.delete("/labels/<label_id>")
@login_required
def delete_label(label_id):
    db.session.delete(_get(label_id))
    db.session.commit()
    return "", 204
