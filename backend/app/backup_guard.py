"""Refuse writes while a Home Assistant backup of this add-on is in progress.

`backup_hook.py pre` writes FLAG after taking the consistent database copy and
`post` removes it. While it exists nothing may change the database, so the
copy in the backup is never older than the live files beside it and a restore
can always promote it. Two layers: a before_request that answers mutating API
calls with a curated 503 + Retry-After, and a before_flush backstop for every
other writer (job worker, token bookkeeping, chat tools).

A crash between `pre` and `post` must not freeze writes forever: the
entrypoint deletes the flag at boot, and a flag older than BACKUP_FLAG_MAX_AGE
is ignored and removed here.
"""
import logging
import os
import time

from flask import current_app, has_app_context, jsonify, request
from sqlalchemy import event

from .extensions import db
from .logging_setup import request_id_var

_LOGGER = logging.getLogger(__name__)

FLAG = os.path.join("backups", ".backup-in-progress")
COPY = os.path.join("backups", "ha-backup.db")  # backup_hook.BACKUP_NAME
BACKUP_FLAG_MAX_AGE = 2 * 3600  # far longer than any HA backup of one add-on
MESSAGE = "A Home Assistant backup is in progress. Try again in a moment."
RETRY_AFTER_S = 10
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Login writes nothing we care to block on and must keep working; the health
# probes are reads.
# Logout must work too: a user has to be able to sign out, and its only write
# (closing vault unlocks) is skipped during a backup — see api/users.logout.
_EXEMPT = frozenset({"/api/v1/users/login", "/api/v1/users/logout"})


class BackupInProgress(Exception):
    """A write was attempted while the backup flag is set. Its message is
    curated and safe to show."""

    def __init__(self):
        super().__init__(MESSAGE)


def backup_in_progress(data_dir) -> bool:
    """True while a fresh backup flag exists. One stat, nothing cached."""
    path = os.path.join(data_dir, FLAG)
    try:
        age = time.time() - os.stat(path).st_mtime
    except FileNotFoundError:
        return False
    if age <= BACKUP_FLAG_MAX_AGE:
        return True
    # Stale: `post` never ran and the add-on wasn't restarted. Drop the flag,
    # and the copy with it: writes resume now, so that copy is no longer
    # current and must not be promoted over them at the next boot.
    for stale in (path, os.path.join(data_dir, COPY)):
        try:
            os.remove(stale)
        except FileNotFoundError:
            pass
    _LOGGER.warning("ignored a backup-in-progress flag %.0fs old; writes resumed", age)
    return False


def paused() -> bool:
    """backup_in_progress() for the current app; False outside an app context."""
    return has_app_context() and backup_in_progress(current_app.config["DATA_DIR"])


def refuse_during_backup() -> None:
    """Explicit check for bulk Query.delete/update, which bypass before_flush."""
    if paused():
        raise BackupInProgress()


def _response():
    resp = jsonify({"error": MESSAGE, "requestId": request_id_var.get()})
    resp.status_code = 503
    resp.headers["Retry-After"] = str(RETRY_AFTER_S)
    return resp


def _refuse_mutations():
    if request.method not in _MUTATING or not request.path.startswith("/api/") \
            or request.path in _EXEMPT:
        return None
    if backup_in_progress(current_app.config["DATA_DIR"]):
        return _response()
    return None


def _before_flush(session, flush_context, instances):
    if not (session.new or session.dirty or session.deleted) or not has_app_context():
        return
    if backup_in_progress(current_app.config["DATA_DIR"]):
        raise BackupInProgress()


def install(app):
    app.before_request(_refuse_mutations)
    app.register_error_handler(BackupInProgress, lambda _e: _response())
    if not event.contains(db.session, "before_flush", _before_flush):
        event.listen(db.session, "before_flush", _before_flush)
