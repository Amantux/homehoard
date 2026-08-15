"""Full-backup download: a consistent snapshot of everything durable.

Owner-only download of a ZIP holding a consistent SQLite snapshot plus the
attachments directory — the on-demand, in-app counterpart of
``scripts/backup.py`` (see docs/disaster-recovery.md).
"""
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, send_file

from ..auth import owner_required
from ..extensions import db

bp = Blueprint("backup", __name__)


@bp.get("/backup")
@owner_required
def download_backup():
    """Stream a ZIP containing a consistent SQLite snapshot + attachments.

    The DB snapshot is taken with sqlite3's online backup API — never a raw
    file copy, which would tear a live WAL database mid-write.

    Owner-only, deliberately: the database file inherently contains hidden
    (vault) items in PLAINTEXT — the vault passphrase gates the UI/API views,
    not the storage — and that completeness is exactly what makes this a full
    backup. A member must not be able to bulk-exfiltrate the vault this way.

    Restore is intentionally NOT offered here: restoring onto a live add-on
    (Supervisor-managed /data) is a documented open problem — see
    docs/disaster-recovery.md ("Not yet covered") and
    docs/runbooks/restore-failure.md for the manual stop→restore→verify runbook.
    """
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite"):
        return jsonify({
            "error": "full backup applies to the built-in SQLite database only; "
                     "back up your PostgreSQL server with pg_dump"
        }), 400

    src_db = db.engine.url.database

    tmpdir = tempfile.mkdtemp(prefix="hbox-backup-")
    snap_path = os.path.join(tmpdir, "homehoard.db")
    zip_path = os.path.join(tmpdir, "backup.zip")
    try:
        # 1) Consistent snapshot via the online backup API (WAL-safe).
        src = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
        dst = sqlite3.connect(snap_path)
        try:
            with dst:
                src.backup(dst)
        finally:
            src.close()
            dst.close()

        # 2) Zip the snapshot + attachments. Written to a temp file (not RAM)
        #    so a large photo library doesn't balloon the worker.
        att_dir = current_app.config["attachments_dir"]()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snap_path, "homehoard.db")
            if os.path.isdir(att_dir):
                for name in sorted(os.listdir(att_dir)):
                    p = os.path.join(att_dir, name)
                    if os.path.isfile(p):
                        zf.write(p, f"attachments/{name}")
        os.remove(snap_path)

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        resp = send_file(
            open(zip_path, "rb"),  # noqa: SIM115 - closed by Flask after streaming
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"homehoard-backup-{stamp}.zip",
        )
        # The open fd keeps streaming after unlink; nothing is left on disk.
        os.remove(zip_path)
        os.rmdir(tmpdir)
        return resp
    except Exception:
        # Best-effort cleanup; never leak paths in the response.
        for p in (snap_path, zip_path):
            if os.path.exists(p):
                os.remove(p)
        if os.path.isdir(tmpdir):
            os.rmdir(tmpdir)
        current_app.logger.exception("full-backup download failed")
        return jsonify({"error": "backup failed"}), 500
