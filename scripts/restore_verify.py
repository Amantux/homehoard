#!/usr/bin/env python3
"""Restore-verification for a HomeHoard backup — proves a backup is recoverable.

Given a backup produced by scripts/backup.py, this:
  1. copies it into an ISOLATED temp dir (never touches prod / the source),
  2. verifies checksums against the manifest,
  3. runs SQLite integrity_check + quick_check,
  4. boots the real application against the restored data dir,
  5. validates readiness and runs representative queries,
  6. confirms the restored row counts match the backup manifest,
  7. writes a machine- and human-readable report, then cleans up.

Exit code 0 iff every check passes. This is safe to run in CI.

Usage:
  python scripts/restore_verify.py --backup /backups/homehoard-<ts> \
      [--report restore-report.json] [--keep]
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone

# Make the backend package importable regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "backend"))


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _boot_and_query(data_dir: str, expected_items):
    """Start the app against the restored data dir and exercise it. Returns a
    list of (name, ok, detail) check tuples."""
    from app import create_app
    from app.config import Config

    class RestoreConfig(Config):
        DATA_DIR = data_dir
        DATABASE_URL = None            # use the restored sqlite file in DATA_DIR
        DISABLE_AUTH = True            # single-tenant probe; no secret required
        RATELIMIT_ENABLED = False
        PROXY_HOPS = 0

    checks = []
    app = create_app(RestoreConfig)   # runs create_all + _migrate → schema check
    checks.append(("schema_migrate", True, "create_all + _migrate succeeded"))
    client = app.test_client()

    r = client.get("/api/v1/ready")
    checks.append(("readiness", r.status_code == 200, f"HTTP {r.status_code}"))

    items = client.get("/api/v1/items?pageSize=5")
    total = items.get_json().get("total") if items.status_code == 200 else None
    checks.append(("items_query", items.status_code == 200, f"total={total}"))
    if expected_items is not None:
        checks.append((
            "item_count_matches_backup",
            total == expected_items,
            f"restored={total} manifest={expected_items}",
        ))

    locs = client.get("/api/v1/locations")
    checks.append(("locations_query", locs.status_code == 200,
                   f"HTTP {locs.status_code}"))
    search = client.get("/api/v1/search?q=a")
    checks.append(("search_query", search.status_code == 200,
                   f"HTTP {search.status_code}"))

    # Stability / no-side-effect: the same read twice yields the same total.
    again = client.get("/api/v1/items?pageSize=5").get_json().get("total")
    checks.append(("read_is_stable", again == total, f"{total} == {again}"))
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", required=True, help="dir produced by backup.py")
    ap.add_argument("--report", default="restore-report.json")
    ap.add_argument("--keep", action="store_true", help="keep the temp restore dir")
    args = ap.parse_args()

    t0 = time.monotonic()
    manifest = json.load(open(os.path.join(args.backup, "manifest.json")))
    checks = []

    workdir = tempfile.mkdtemp(prefix="homehoard-restore-")
    try:
        # 1) Restore DB + verify checksum.
        db_dst = os.path.join(workdir, "homehoard.db")
        shutil.copy2(os.path.join(args.backup, "homehoard.db"), db_dst)
        db_ok = _sha256(db_dst) == manifest["database"]["sha256"]
        checks.append(("db_checksum", db_ok, "sha256 matches manifest"))

        # 2) Restore attachments + verify checksum.
        att_tar = os.path.join(args.backup, "attachments.tar.gz")
        att_ok = _sha256(att_tar) == manifest["attachments"]["sha256"]
        checks.append(("attachments_checksum", att_ok, "sha256 matches manifest"))
        att_dir = os.path.join(workdir, "attachments")
        os.makedirs(att_dir, exist_ok=True)
        if os.path.getsize(att_tar) > 0:
            with tarfile.open(att_tar) as tar:
                # Backups store basenames only, but validate anyway (no absolute
                # paths, no traversal) before extracting into the isolated dir.
                for m in tar.getmembers():
                    if m.name.startswith("/") or ".." in m.name.split("/"):
                        raise ValueError(f"unsafe tar member: {m.name}")
                try:
                    tar.extractall(att_dir, filter="data")  # py>=3.12: blocks unsafe members
                except TypeError:
                    tar.extractall(att_dir)  # older Python: members validated above

        # 3) SQLite integrity checks on the restored DB.
        conn = sqlite3.connect(db_dst)
        integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
        quick = conn.execute("PRAGMA quick_check").fetchone()[0]
        conn.close()
        checks.append(("integrity_check", integ == "ok", integ))
        checks.append(("quick_check", quick == "ok", quick))

        # 4-7) Boot the app against restored state and query it.
        expected_items = manifest["database"]["counts"].get("items")
        checks.extend(_boot_and_query(workdir, expected_items))
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)

    elapsed = round(time.monotonic() - t0, 2)
    passed = all(ok for _, ok, _ in checks)
    report = {
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "backup": os.path.abspath(args.backup),
        "backupCreatedAt": manifest.get("createdAt"),
        "elapsedSeconds": elapsed,
        "passed": passed,
        "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
    }
    with open(args.report, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nRestore verification: {'PASS' if passed else 'FAIL'}  ({elapsed}s)")
    for n, ok, d in checks:
        print(f"  [{'OK ' if ok else 'FAIL'}] {n:<28} {d}")
    print(f"\nReport → {args.report}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
