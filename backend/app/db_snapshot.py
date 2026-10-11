"""Pre-upgrade SQLite snapshot.

Taken by _run_migrations() right before Alembic applies pending revisions to an
existing SQLite database, so a migration that fails (or is SIGKILLed mid-DDL)
never leaves the user without a copy of their data. Uses the same online
`sqlite3.Connection.backup()` API as scripts/backup.py, which yields a
consistent copy even if another connection holds the file open.
"""
import glob
import logging
import os
import sqlite3
from datetime import datetime, timezone

_LOGGER = logging.getLogger(__name__)

KEEP = 2   # newest pre-upgrade snapshots retained; older ones are rotated out


class SnapshotError(RuntimeError):
    """The pre-upgrade snapshot could not be written. Carries a curated message;
    the caller must refuse to migrate."""


def snapshot_sqlite(db_path, data_dir, current_rev):
    """Copy `db_path` to <data_dir>/backups/pre-upgrade-<rev>-<UTC stamp>.db
    (mode 0600), keep the newest KEEP snapshots, and return the new path."""
    backups = os.path.join(data_dir, "backups")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dst = os.path.join(backups, f"pre-upgrade-{current_rev}-{stamp}.db")
    try:
        os.makedirs(backups, exist_ok=True)
        # Create the file 0600 up front so the copy is never world-readable,
        # even for the instant before a chmod.
        os.close(os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        src = sqlite3.connect(db_path)
        try:
            out = sqlite3.connect(dst)
            try:
                src.backup(out)
            finally:
                out.close()
        finally:
            src.close()
    except (OSError, sqlite3.Error) as exc:
        _LOGGER.error("pre-upgrade snapshot failed: %s", exc.__class__.__name__)
        try:
            os.remove(dst)
        except OSError:
            pass
        raise SnapshotError(
            "Could not back up the database before upgrading it (is the data "
            f"directory full or read-only? check {backups}). The upgrade was NOT "
            "applied and your data is unchanged; free space and restart."
        ) from exc

    _LOGGER.warning("pre-upgrade snapshot of the database written to %s", dst)
    _rotate(backups)
    return dst


def _rotate(backups):
    # mtime orders across revisions (the rev name sorts before the stamp in the
    # filename); the name breaks an mtime tie within one revision.
    snaps = sorted(glob.glob(os.path.join(backups, "pre-upgrade-*.db")),
                   key=lambda p: (os.path.getmtime(p), p))
    for old in snaps[:-KEEP]:
        try:
            os.remove(old)
        except OSError as exc:
            _LOGGER.warning("could not remove old snapshot %s (%s)", old,
                            exc.__class__.__name__)
