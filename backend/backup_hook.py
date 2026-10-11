"""Home Assistant hot-backup hooks.

homehoard/config.yaml sets `backup: hot` with
  backup_pre:  python3 /app/backend/backup_hook.py pre
  backup_post: python3 /app/backend/backup_hook.py post
and writes a consistent copy with SQLite's online backup API to
<DATA_DIR>/backups/ha-backup.db, which the tar picks up next to the live
homehoard.db (+ -wal/-shm); `post` removes it. The live files travel too, so
a backup of a STOPPED add-on (no hooks run) still holds the database, and is
consistent because nothing was writing.

`pre` then writes FLAG; while it exists the app refuses every write
(app/backup_guard.py), so nothing in the live files is newer than the copy.
`post` removes the flag, then the copy.

`restore-if-needed` (run by the entrypoint before the app starts) puts the
copy in place whenever one exists: after an HA restore the live files may be
torn, and after a crash between `pre` and `post` the copy holds every write
because none were allowed since. A live database that fails `PRAGMA
quick_check` is kept aside first.

The Supervisor runs these with `docker exec` (as root, the image's env, no
shell): paths are absolute, settings come from the same adapter the app uses,
and a non-zero exit makes the Supervisor fail this add-on's backup rather than
store one without a database.
"""
import os
import sqlite3
import sys
from datetime import datetime, timezone

BACKUP_NAME = "ha-backup.db"
# Must match app/backup_guard.py FLAG.
FLAG = ".backup-in-progress"


class HookError(RuntimeError):
    """Curated, user-facing failure; carries no paths' contents or secrets."""


def _sqlite_path(db_url):
    """The database file for a SQLite URL, or None for any other backend."""
    from sqlalchemy.engine import make_url
    url = make_url(db_url)
    if url.get_backend_name() != "sqlite":
        return None
    if not url.database or url.database == ":memory:":
        return None
    return os.path.abspath(url.database)


def _match_owner(path, like):
    # Running as root (docker exec): hand the file to whoever owns the data
    # dir (the app user), so the app can read/replace it later.
    if os.geteuid() == 0:
        st = os.stat(like)
        os.chown(path, st.st_uid, st.st_gid)


def _sqlite_copy(src_path, dst_path, owner_like):
    """Consistent copy via the online backup API, written to a temp file first
    (0600 from creation) and renamed into place only once it checks out."""
    tmp = dst_path + ".tmp"
    try:
        os.remove(tmp)
    except FileNotFoundError:
        pass
    os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    try:
        src = sqlite3.connect(src_path)
        try:
            out = sqlite3.connect(tmp)
            try:
                src.backup(out)
                if out.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise HookError("the database copy failed its integrity check")
            finally:
                out.close()
        finally:
            src.close()
        _match_owner(tmp, owner_like)
        os.replace(tmp, dst_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _quick_check_ok(path):
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _pre(db_path, data_dir):
    if not os.path.exists(db_path):
        print("homehoard backup: no database yet, nothing to snapshot")
        return
    backups = os.path.join(data_dir, "backups")
    os.makedirs(backups, exist_ok=True)
    _match_owner(backups, data_dir)
    _sqlite_copy(db_path, os.path.join(backups, BACKUP_NAME), data_dir)
    # Only after the copy succeeded: from here on the app refuses writes.
    flag = os.path.join(backups, FLAG)
    os.close(os.open(flag, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))
    os.utime(flag)  # an old leftover flag must not look stale to the app
    _match_owner(flag, data_dir)
    print("homehoard backup: consistent database copy written; writes paused")


def _post(data_dir):
    for name in (FLAG, BACKUP_NAME):  # flag first: resume writes promptly
        try:
            os.remove(os.path.join(data_dir, "backups", name))
        except FileNotFoundError:
            pass


def _restore_if_needed(db_path, data_dir):
    copy = os.path.join(data_dir, "backups", BACKUP_NAME)
    if not os.path.exists(copy):
        return
    copy_mtime = os.stat(copy).st_mtime
    copy_when = datetime.fromtimestamp(copy_mtime, timezone.utc).isoformat(timespec="seconds")
    age = datetime.now(timezone.utc).timestamp() - copy_mtime
    # Promote unconditionally: no write was allowed after `pre` (FLAG), so the
    # copy is never behind a healthy live database, and may be ahead of a torn one.
    if os.path.exists(db_path) and not _quick_check_ok(db_path):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        os.replace(db_path, f"{db_path}.corrupt-{stamp}")
        print(f"homehoard restore: database failed its integrity check; "
              f"kept aside as {os.path.basename(db_path)}.corrupt-{stamp}")
    # A WAL/SHM left beside a replaced main file would be replayed into it.
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(db_path + suffix)
        except FileNotFoundError:
            pass
    _sqlite_copy(copy, db_path, data_dir)
    os.remove(copy)
    try:
        os.remove(os.path.join(data_dir, "backups", FLAG))
    except FileNotFoundError:
        pass
    print(f"homehoard restore: restored consistent copy from HA backup "
          f"(copy {copy_when}, {age:.0f}s old)")


def run(cmd, db_url, data_dir):
    if cmd not in ("pre", "post", "restore-if-needed"):
        print("usage: backup_hook.py pre|post|restore-if-needed", file=sys.stderr)
        return 2
    db_path = _sqlite_path(db_url)
    if db_path is None:
        print("homehoard backup: postgres: nothing to snapshot "
              "(back the database up with pg_dump)")
        return 0
    try:
        if cmd == "pre":
            _pre(db_path, data_dir)
        elif cmd == "post":
            _post(data_dir)
        else:
            _restore_if_needed(db_path, data_dir)
    except (OSError, sqlite3.Error, HookError) as exc:
        print(f"homehoard backup: {cmd} failed ({exc.__class__.__name__}); is the "
              f"data directory full or read-only? check {data_dir}/backups",
              file=sys.stderr)
        return 1
    return 0


def main(argv):
    if len(argv) != 1:
        return run("", "", "")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app.settings import load_settings
    settings = load_settings(validate=False)
    return run(argv[0], settings.sqlalchemy_uri, settings.data_dir)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
