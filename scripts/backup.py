#!/usr/bin/env python3
"""Online backup of HomeHoard's durable state (SQLite DB + attachments).

Durable state lives under HBOX_DATA_DIR:
  - homehoard.db      → the whole inventory (SQLite; backed up with the online
                        .backup API so it's consistent even while the app runs)
  - attachments/      → uploaded item/bin photos and documents

Everything else (the in-memory rate limiter, the derived frontend build) is
reconstructable and NOT backed up.

Usage:
  python scripts/backup.py --data-dir /data --out /backups/homehoard-<ts>

Produces, in --out:
  homehoard.db, attachments.tar.gz, manifest.json (checksums + counts + sizes).
Exit code 0 on success. Never writes to the source data dir.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import tarfile
from datetime import datetime, timezone


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _counts(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        out = {}
        for table in ("items", "bins", "locations", "labels", "users", "groups"):
            try:
                out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                out[table] = None  # table absent (fresh DB)
        return out
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.environ.get("HBOX_DATA_DIR", "./data"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    src_db = os.path.join(args.data_dir, "homehoard.db")
    src_att = os.path.join(args.data_dir, "attachments")
    if not os.path.exists(src_db):
        print(f"ERROR: no database at {src_db}")
        return 1
    os.makedirs(args.out, exist_ok=True)

    # 1) Consistent online DB backup (safe while the app is writing, incl. WAL).
    dst_db = os.path.join(args.out, "homehoard.db")
    src = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    dst = sqlite3.connect(dst_db)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()

    # 2) Attachments tarball (best-effort; dir may not exist yet).
    dst_att = os.path.join(args.out, "attachments.tar.gz")
    att_count = 0
    if os.path.isdir(src_att):
        with tarfile.open(dst_att, "w:gz") as tar:
            for name in sorted(os.listdir(src_att)):
                tar.add(os.path.join(src_att, name), arcname=name)
                att_count += 1
    else:
        open(dst_att, "wb").close()  # empty marker so restore is uniform

    manifest = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "source": os.path.abspath(args.data_dir),
        "database": {
            "file": "homehoard.db",
            "sha256": _sha256(dst_db),
            "bytes": os.path.getsize(dst_db),
            "counts": _counts(dst_db),
        },
        "attachments": {
            "file": "attachments.tar.gz",
            "sha256": _sha256(dst_att),
            "bytes": os.path.getsize(dst_att),
            "count": att_count,
        },
    }
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    c = manifest["database"]["counts"]
    print(f"Backup OK → {args.out}")
    print(f"  db: {manifest['database']['bytes']} bytes  "
          f"items={c.get('items')} bins={c.get('bins')} locations={c.get('locations')}")
    print(f"  attachments: {att_count} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
