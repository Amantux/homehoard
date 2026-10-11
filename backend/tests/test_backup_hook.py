"""Hot Home Assistant backups (backend/backup_hook.py, wired as backup_pre /
backup_post in homehoard/config.yaml).

The Supervisor tars /data while the add-on keeps running. The live SQLite
files travel too, but a file copy of them can be torn, so the copy `pre`
writes is the database a restore prefers. That copy must be consistent even
while another connection is writing, and must hold committed rows only.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backup_hook  # noqa: E402


def _live_db(tmp_path):
    """A WAL database with 2000 committed rows, all still in the WAL (no
    checkpoint), plus an open writer mid-transaction holding uncommitted rows."""
    path = tmp_path / "homehoard.db"
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("BEGIN")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [("x" * 200,)] * 2000)
    conn.execute("COMMIT")
    conn.execute("BEGIN")
    conn.execute("INSERT INTO t (v) VALUES ('uncommitted')")
    return path, conn


def _url(path):
    return f"sqlite:///{path}"


def test_pre_copies_committed_rows_consistently_while_a_writer_is_open(tmp_path):
    db_path, writer = _live_db(tmp_path)
    try:
        assert backup_hook.run("pre", _url(db_path), str(tmp_path)) == 0
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    out = tmp_path / "backups" / backup_hook.BACKUP_NAME
    assert out.exists()
    assert oct(out.stat().st_mode & 0o777) == "0o600"
    flag = tmp_path / "backups" / backup_hook.FLAG  # app refuses writes from here
    assert flag.exists()
    assert oct(flag.stat().st_mode & 0o777) == "0o600"
    # The copy is a self-contained database: no WAL needed beside it.
    assert not (tmp_path / "backups" / (backup_hook.BACKUP_NAME + "-wal")).exists()
    copy = sqlite3.connect(out)
    try:
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert copy.execute("SELECT count(*) FROM t").fetchone()[0] == 2000
        assert copy.execute("SELECT count(*) FROM t WHERE v='uncommitted'").fetchone()[0] == 0
    finally:
        copy.close()


def test_post_removes_the_flag_and_the_copy_and_is_idempotent(tmp_path):
    db_path, writer = _live_db(tmp_path)
    writer.execute("ROLLBACK")
    writer.close()
    assert backup_hook.run("pre", _url(db_path), str(tmp_path)) == 0
    assert backup_hook.run("post", _url(db_path), str(tmp_path)) == 0
    assert not (tmp_path / "backups" / backup_hook.BACKUP_NAME).exists()
    assert not (tmp_path / "backups" / backup_hook.FLAG).exists()
    assert backup_hook.run("post", _url(db_path), str(tmp_path)) == 0


def test_pre_on_postgres_exits_zero_without_touching_disk(tmp_path, capsys):
    rc = backup_hook.run("pre", "postgresql+psycopg://u:secret@db/hh", str(tmp_path))
    assert rc == 0
    assert list(tmp_path.iterdir()) == []
    out = capsys.readouterr()
    assert "nothing to snapshot" in out.out
    assert "secret" not in out.out + out.err


def test_pre_fails_loudly_when_the_copy_cannot_be_written(tmp_path, capsys):
    db_path, writer = _live_db(tmp_path)
    writer.execute("ROLLBACK")
    writer.close()
    (tmp_path / "backups").write_text("not a directory")
    assert backup_hook.run("pre", _url(db_path), str(tmp_path)) == 1
    assert "backup" in capsys.readouterr().err.lower()


def test_unknown_command_is_rejected(tmp_path):
    assert backup_hook.run("bogus", _url(tmp_path / "x.db"), str(tmp_path)) == 2


def _restored_tree(tmp_path):
    """/data holding the copy but no live DB."""
    db_path, writer = _live_db(tmp_path)
    writer.execute("ROLLBACK")
    writer.close()
    assert backup_hook.run("pre", _url(db_path), str(tmp_path)) == 0
    for suffix in ("", "-wal", "-shm"):
        p = tmp_path / ("homehoard.db" + suffix)
        if p.exists():
            p.unlink()
    return db_path


def test_restore_if_needed_puts_the_copy_in_place_when_the_db_is_missing(tmp_path):
    db_path = _restored_tree(tmp_path)
    assert backup_hook.run("restore-if-needed", _url(db_path), str(tmp_path)) == 0
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 2000
    finally:
        conn.close()
    assert not (tmp_path / "backups" / backup_hook.BACKUP_NAME).exists()


def _set_mtime(path, when):
    os.utime(path, (when, when))


def _copy_vs_live_tree(tmp_path, live_minus_copy):
    """A healthy live DB with one row more than the copy `pre` wrote, plus
    stale -wal/-shm files; mtimes set so the live files are `live_minus_copy`
    seconds newer than the copy (negative: the copy is newer). Small gaps are
    an HA restore (`pre` ran just before the tar); large ones a leftover from a
    backup whose `post` never ran."""
    db_path, writer = _live_db(tmp_path)
    writer.execute("ROLLBACK")
    assert backup_hook.run("pre", _url(db_path), str(tmp_path)) == 0
    writer.execute("INSERT INTO t (v) VALUES ('live only')")
    writer.close()
    for suffix in ("-wal", "-shm"):
        (tmp_path / ("homehoard.db" + suffix)).write_bytes(b"stale")
    copy = tmp_path / "backups" / backup_hook.BACKUP_NAME
    copy_t = 2_000_000_000
    _set_mtime(copy, copy_t)
    for suffix in ("", "-wal", "-shm"):
        _set_mtime(tmp_path / ("homehoard.db" + suffix), copy_t + live_minus_copy)
    return db_path, copy


def test_restore_if_needed_promotes_the_copy_over_a_healthy_live_db(tmp_path, capsys):
    # Writes are refused after `pre`, so the copy is current in both the
    # restore and the leftover case, however much newer the live files look.
    db_path, copy = _copy_vs_live_tree(tmp_path, live_minus_copy=3600)
    flag = tmp_path / "backups" / backup_hook.FLAG
    assert flag.exists()
    assert backup_hook.run("restore-if-needed", _url(db_path), str(tmp_path)) == 0
    assert not copy.exists()
    assert not flag.exists()
    assert not (tmp_path / "homehoard.db-wal").exists()
    assert not (tmp_path / "homehoard.db-shm").exists()
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 2000
    finally:
        conn.close()
    out = capsys.readouterr().out
    assert "restored consistent copy from HA backup" in out
    assert "2033-05-18" in out  # the copy's mtime (2_000_000_000), in UTC


def test_restore_if_needed_replaces_a_corrupt_db_and_keeps_it_aside(tmp_path):
    db_path = _restored_tree(tmp_path)
    db_path.write_bytes(b"garbage" * 1000)
    assert backup_hook.run("restore-if-needed", _url(db_path), str(tmp_path)) == 0
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 2000
    finally:
        conn.close()
    assert list(tmp_path.glob("homehoard.db.corrupt-*"))


def test_main_resolves_paths_through_the_settings_adapter(tmp_path, monkeypatch):
    db_path, writer = _live_db(tmp_path)
    writer.execute("ROLLBACK")
    writer.close()
    monkeypatch.setenv("HBOX_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HBOX_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert backup_hook.main(["pre"]) == 0
    assert (tmp_path / "backups" / backup_hook.BACKUP_NAME).exists()


# --- The hook runs as root over /data, which the app user owns: it must never
# follow a link the app user planted (chown or write anywhere as root).
# Exercised as the current user in a temp dir; root itself is not exercised.

def _plain_db(tmp_path):
    db_path, writer = _live_db(tmp_path)
    writer.execute("ROLLBACK")
    writer.close()
    return db_path


def test_pre_refuses_a_symlinked_backups_dir(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    db_path = _plain_db(data)
    (data / "backups").symlink_to(victim)
    assert backup_hook.run("pre", _url(db_path), str(data)) == 1
    assert list(victim.iterdir()) == []  # nothing written through the link
    err = capsys.readouterr().err
    assert "symbolic link" in err and "refusing" in err


def test_pre_does_not_clobber_a_symlinked_flag_target(tmp_path):
    db_path = _plain_db(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / backup_hook.FLAG).symlink_to(victim)
    assert backup_hook.run("pre", _url(db_path), str(tmp_path)) == 0
    flag = tmp_path / "backups" / backup_hook.FLAG
    assert not flag.is_symlink() and flag.is_file()  # the link itself was replaced
    assert victim.read_text() == "precious"


def test_pre_refuses_a_symlinked_live_db(tmp_path):
    real = _plain_db(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    (data / "homehoard.db").symlink_to(real)
    assert backup_hook.run("pre", _url(data / "homehoard.db"), str(data)) == 1
    assert not (data / "backups" / backup_hook.BACKUP_NAME).exists()


def test_restore_refuses_a_symlinked_live_db(tmp_path, capsys):
    db_path = _restored_tree(tmp_path)
    victim = tmp_path / "victim.db"
    victim.write_text("precious")
    db_path.symlink_to(victim)
    assert backup_hook.run("restore-if-needed", _url(db_path), str(tmp_path)) == 1
    assert victim.read_text() == "precious"
    assert db_path.is_symlink()
    assert (tmp_path / "backups" / backup_hook.BACKUP_NAME).exists()  # kept for a retry
    assert "symbolic link" in capsys.readouterr().err


def test_restore_refuses_a_symlinked_copy(tmp_path):
    db_path = _restored_tree(tmp_path)
    copy = tmp_path / "backups" / backup_hook.BACKUP_NAME
    other = tmp_path / "elsewhere.db"
    copy.rename(other)
    copy.symlink_to(other)
    assert backup_hook.run("restore-if-needed", _url(db_path), str(tmp_path)) == 1
    assert not db_path.exists()


def test_post_refuses_a_symlinked_backups_dir(tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / backup_hook.BACKUP_NAME).write_text("not ours")
    data = tmp_path / "data"
    data.mkdir()
    (data / "backups").symlink_to(victim)
    assert backup_hook.run("post", _url(data / "homehoard.db"), str(data)) == 1
    assert (victim / backup_hook.BACKUP_NAME).exists()


def test_the_copy_leaves_no_temp_files_behind(tmp_path):
    db_path = _plain_db(tmp_path)
    assert backup_hook.run("pre", _url(db_path), str(tmp_path)) == 0
    assert sorted(p.name for p in (tmp_path / "backups").iterdir()) == sorted(
        [backup_hook.BACKUP_NAME, backup_hook.FLAG])
