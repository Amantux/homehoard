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
import secrets
import sqlite3
import stat
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


def _owner_of(like):
    """(uid, gid) to hand created files to when running as root (docker
    exec): whoever owns the data dir (the app user). None when not root."""
    if os.geteuid() != 0:
        return None
    st = os.stat(like)
    return st.st_uid, st.st_gid


# The app user owns /data, and this hook runs as root: every path below /data
# may be a link the app user planted. So nothing here follows a link: dirs are
# lstat-checked and then used only through an O_NOFOLLOW fd (dir_fd=...),
# files are created O_EXCL|O_NOFOLLOW, chown never follows, and the SQLite
# temp copy lives in a fresh root-only dir the app user cannot write into.
def _refuse_link(path, kind):
    """lstat `path`; refuse a symlink or anything but `kind` (S_ISDIR/S_ISREG).
    Returns False when it does not exist."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(st.st_mode):
        raise HookError(f"{os.path.basename(path)} is a symbolic link; refusing")
    if not kind(st.st_mode):
        raise HookError(f"{os.path.basename(path)} is not what it should be; refusing")
    return True


def _open_dir(path, root=None):
    """An fd on the real directory `path` (not a link; under `root` if given)."""
    if not _refuse_link(path, stat.S_ISDIR):
        raise FileNotFoundError(path)
    if root is not None and not os.path.realpath(path).startswith(
            os.path.realpath(root) + os.sep):
        raise HookError(f"{os.path.basename(path)} is outside the data directory; refusing")
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _fd_path(dir_fd, name):
    # Resolves through the already-open directory, whatever its path now names.
    return f"/proc/self/fd/{dir_fd}/{name}"


def _sqlite_copy(src_path, dst_dir_fd, name, owner):
    """Consistent copy of `src_path` via the online backup API into
    `name` inside `dst_dir_fd`: written in a private 0700 dir first (0600 from
    creation) and renamed into place only once it checks out."""
    priv = f".{name}.tmp-{os.getpid()}-{secrets.token_hex(4)}"
    os.mkdir(priv, 0o700, dir_fd=dst_dir_fd)
    try:
        pfd = os.open(priv, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dst_dir_fd)
        try:
            if os.fstat(pfd).st_uid != os.geteuid():  # swapped under us
                raise HookError("the temporary directory was replaced; refusing")
            os.close(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=pfd))
            src = sqlite3.connect(src_path)
            try:
                out = sqlite3.connect(_fd_path(pfd, name))
                try:
                    src.backup(out)
                    if out.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise HookError("the database copy failed its integrity check")
                finally:
                    out.close()
            finally:
                src.close()
            if owner:
                os.chown(name, *owner, dir_fd=pfd, follow_symlinks=False)
            # rename() replaces a link at the destination; it never follows it.
            os.replace(name, name, src_dir_fd=pfd, dst_dir_fd=dst_dir_fd)
        finally:
            for leftover in os.listdir(pfd):
                os.remove(leftover, dir_fd=pfd)
            os.close(pfd)
    finally:
        os.rmdir(priv, dir_fd=dst_dir_fd)


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
    if not _refuse_link(db_path, stat.S_ISREG):
        print("homehoard backup: no database yet, nothing to snapshot")
        return
    os.close(_open_dir(data_dir))  # /data itself must be a real directory
    owner = _owner_of(data_dir)
    backups = os.path.join(data_dir, "backups")
    try:
        os.mkdir(backups, 0o700)
    except FileExistsError:
        pass
    bfd = _open_dir(backups, root=data_dir)
    try:
        if owner:
            os.fchown(bfd, *owner)
        _sqlite_copy(db_path, bfd, BACKUP_NAME, owner)
        # Only after the copy succeeded: from here on the app refuses writes.
        # Remove-then-create-exclusive: a planted link is unlinked, never
        # followed, and a fresh file can't look stale to the app.
        try:
            os.remove(FLAG, dir_fd=bfd)
        except FileNotFoundError:
            pass
        fd = os.open(FLAG, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=bfd)
        try:
            if owner:
                os.fchown(fd, *owner)
        finally:
            os.close(fd)
    finally:
        os.close(bfd)
    print("homehoard backup: consistent database copy written; writes paused")


def _post(data_dir):
    try:
        bfd = _open_dir(os.path.join(data_dir, "backups"), root=data_dir)
    except FileNotFoundError:
        return
    try:
        for name in (FLAG, BACKUP_NAME):  # flag first: resume writes promptly
            try:
                os.remove(name, dir_fd=bfd)  # unlink never follows a link
            except FileNotFoundError:
                pass
    finally:
        os.close(bfd)


def _restore_if_needed(db_path, data_dir):
    try:
        bfd = _open_dir(os.path.join(data_dir, "backups"), root=data_dir)
    except FileNotFoundError:
        return
    try:
        copy = os.path.join(data_dir, "backups", BACKUP_NAME)
        if not _refuse_link(copy, stat.S_ISREG):
            return
        _refuse_link(db_path, stat.S_ISREG)
        dfd = _open_dir(os.path.dirname(db_path))
        try:
            _restore(db_path, data_dir, bfd, dfd)
        finally:
            os.close(dfd)
    finally:
        os.close(bfd)


def _restore(db_path, data_dir, bfd, dfd):
    db_name = os.path.basename(db_path)
    copy_mtime = os.stat(BACKUP_NAME, dir_fd=bfd, follow_symlinks=False).st_mtime
    copy_when = datetime.fromtimestamp(copy_mtime, timezone.utc).isoformat(timespec="seconds")
    age = datetime.now(timezone.utc).timestamp() - copy_mtime
    # Promote unconditionally: no write was allowed after `pre` (FLAG), so the
    # copy is never behind a healthy live database, and may be ahead of a torn one.
    if _refuse_link(db_path, stat.S_ISREG) and not _quick_check_ok(_fd_path(dfd, db_name)):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        os.replace(db_name, f"{db_name}.corrupt-{stamp}", src_dir_fd=dfd, dst_dir_fd=dfd)
        print(f"homehoard restore: database failed its integrity check; "
              f"kept aside as {db_name}.corrupt-{stamp}")
    # A WAL/SHM left beside a replaced main file would be replayed into it.
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(db_name + suffix, dir_fd=dfd)  # unlink never follows a link
        except FileNotFoundError:
            pass
    _sqlite_copy(_fd_path(bfd, BACKUP_NAME), dfd, db_name, _owner_of(data_dir))
    os.remove(BACKUP_NAME, dir_fd=bfd)
    try:
        os.remove(FLAG, dir_fd=bfd)
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
    except HookError as exc:
        # Curated message (no file contents, no secrets); non-zero aborts the backup.
        print(f"homehoard backup: {cmd} failed: {exc}", file=sys.stderr)
        return 1
    except (OSError, sqlite3.Error) as exc:
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
