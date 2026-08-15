"""Full-backup download endpoint (GET /api/v1/backup)."""
import io
import os
import sqlite3
import zipfile

from app.extensions import db
from app.models import User


def _make_item(auth_client, name="Cordless Drill"):
    r = auth_client.post("/api/v1/items", json={"name": name})
    assert r.status_code in (200, 201), r.get_json()
    return r.get_json()


def test_backup_download_zip_contains_valid_db_with_callers_items(app, auth_client):
    _make_item(auth_client, "Cordless Drill")
    # An attachment file on disk must ride along in the zip.
    with app.app_context():
        att_dir = app.config["attachments_dir"]()
    with open(os.path.join(att_dir, "photo-1.jpg"), "wb") as f:
        f.write(b"jpegbytes")

    r = auth_client.get("/api/v1/backup")

    assert r.status_code == 200
    assert r.mimetype == "application/zip"
    cd = r.headers.get("Content-Disposition", "")
    assert "attachment" in cd and "homehoard-backup-" in cd and ".zip" in cd

    zf = zipfile.ZipFile(io.BytesIO(r.data))
    names = zf.namelist()
    assert "homehoard.db" in names
    assert "attachments/photo-1.jpg" in names

    # The DB member must be a *valid* sqlite database holding the caller's item.
    tmp = os.path.join(str(app.config["DATA_DIR"]), "extracted.db")
    with open(tmp, "wb") as f:
        f.write(zf.read("homehoard.db"))
    conn = sqlite3.connect(tmp)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        rows = conn.execute("SELECT name FROM items").fetchall()
    finally:
        conn.close()
    assert ("Cordless Drill",) in rows


def test_backup_non_owner_returns_403(app, auth_client):
    with app.app_context():
        u = db.session.query(User).filter_by(email="t@t.com").first()
        u.is_owner = False
        db.session.commit()

    r = auth_client.get("/api/v1/backup")

    assert r.status_code == 403


def test_backup_unauthenticated_returns_401(client):
    r = client.get("/api/v1/backup")

    assert r.status_code == 401
