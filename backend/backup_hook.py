"""Home Assistant hot-backup hooks.

homehoard/config.yaml sets `backup: hot` with
  backup_pre:  python3 /app/backend/backup_hook.py pre
  backup_post: python3 /app/backend/backup_hook.py post
and writes a consistent copy with SQLite's online backup API to
<DATA_DIR>/backups/ha-backup.db, which the tar picks up next to the live
homehoard.db (+ -wal/-shm); `post` removes it. The live files travel too, so
a backup of a STOPPED add-on (no hooks run) still holds the database, and is
consistent because nothing was writing.

`restore-if-needed` (run by the entrypoint before the app starts) puts the
copy in place when the live database is missing or fails `PRAGMA
quick_check` (keeping the broken file aside), or when the live files are at
most RESTORE_WINDOW newer than the copy (after an HA restore: the live files
may be torn). A copy older than that is a leftover from a backup whose `post`
never ran, and is deleted.

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
# How much newer than the copy the live files may be and still lose to it on
# restore: generous for the Supervisor tarring this add-on's /data (with
# attachments) right after `pre`. See _restore_if_needed.
RESTORE_WINDOW = 15 * 60


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
    print("homehoard backup: consistent database copy written")


def _post(data_dir):
    try:
        os.remove(os.path.join(data_dir, "backups", BACKUP_NAME))
    except FileNotFoundError:
        pass


def _live_mtime(db_path):
    """Newest mtime among the live main file and its -wal/-shm, or None."""
    times = []
    for suffix in ("", "-wal", "-shm"):
        try:
            times.append(os.stat(db_path + suffix).st_mtime)
        except FileNotFoundError:
            pass
    return max(times) if times else None


def _restore_if_needed(db_path, data_dir):
    copy = os.path.join(data_dir, "backups", BACKUP_NAME)
    if not os.path.exists(copy):
        return
    copy_mtime = os.stat(copy).st_mtime
    copy_when = datetime.fromtimestamp(copy_mtime, timezone.utc).isoformat(timespec="seconds")
    age = datetime.now(timezone.utc).timestamp() - copy_mtime
    if os.path.exists(db_path):
        if _quick_check_ok(db_path):
            # Both exist. Everything in /data looks the same after an HA
            # restore and after a crash between `pre` and `post`, so timing
            # is the only signal. `pre` runs just before the tar, so after a
            # restore the live files (possibly torn) are at most the tar's
            # duration newer than the copy: prefer the copy. (The tar restores
            # mtimes; were it not to, every file would carry extraction time
            # and the copy would still win.) Live files newer than that are a
            # leftover copy's database moving on: discard the copy. A leftover
            # whose add-on restarts within the window loses at most those
            # minutes of writes (a rare double failure); a restore whose tar
            # took longer keeps the live files, which at worst lack the same
            # window's writes that the copy lacks too.
            if _live_mtime(db_path) - copy_mtime > RESTORE_WINDOW:
                os.remove(copy)
                print(f"homehoard restore: discarded a leftover backup copy "
                      f"(copy {copy_when}, {age:.0f}s old) well older than the live database")
                return
        else:
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
