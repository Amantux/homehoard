"""JPEG thumbnails for photo attachments, stored beside the original file.

A thumbnail lives at ``<original path>.thumb.jpg`` — a pure name convention, so
no schema change is needed. Pre-existing photos simply have no thumbnail file
yet; the document route falls back to the original, and the backfill action
(``POST /actions/generate-thumbnails``) fills the gap idempotently.
"""
from __future__ import annotations

import logging
import os

_LOGGER = logging.getLogger("homehoard.thumbnails")

THUMB_SUFFIX = ".thumb.jpg"
MAX_EDGE = 400
QUALITY = 80


def thumb_path(path: str) -> str:
    """Where ``path``'s thumbnail lives (whether or not it exists)."""
    return path + THUMB_SUFFIX


def generate(path: str) -> bool:
    """Write a thumbnail beside ``path``. Returns True if one was written.

    Never raises: a non-image (or unreadable) file simply gets no thumbnail and
    the document route serves the original — an upload must never fail because
    its thumbnail did.
    """
    try:
        from PIL import Image, ImageOps

        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)  # bake in phone-camera rotation
            im.thumbnail((MAX_EDGE, MAX_EDGE))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")  # JPEG has no alpha/palette
            im.save(thumb_path(path), "JPEG", quality=QUALITY)
        return True
    except Exception:  # noqa: BLE001 — any non-image/corrupt file: no thumbnail
        _LOGGER.info("no thumbnail generated for %s", os.path.basename(path))
        return False


def remove(path: str) -> None:
    """Best-effort removal of the thumbnail belonging to ``path``."""
    try:
        os.remove(thumb_path(path))
    except OSError:
        pass


def backfill(group_id: str) -> dict:
    """Generate missing thumbnails for the group's photo attachments.

    Idempotent: photos that already have a thumbnail (or whose file is gone, or
    that turn out not to be images) are skipped, so re-running is always safe.
    """
    from ..extensions import db
    from ..models import Attachment, Document

    docs = (
        db.session.query(Document)
        .join(Attachment, Attachment.document_id == Document.id)
        .filter(Document.group_id == group_id, Attachment.type == "photo")
        .order_by(Document.created_at.asc())
        .all()
    )
    generated = skipped = 0
    for doc in docs:
        if (not doc.path or not os.path.isfile(doc.path)
                or os.path.isfile(thumb_path(doc.path))):
            skipped += 1
            continue
        if generate(doc.path):
            generated += 1
        else:
            skipped += 1
    return {"generated": generated, "skipped": skipped}
