# Runbook: Disk full / `/data` not writable

**Symptom:** `/api/v1/ready` returns 503 with `storage:error` (and/or
`database:error`); uploads/writes fail; log shows `disk I/O error` or `No space
left on device`.

## 1. Confirm
```bash
curl -s http://127.0.0.1:7745/api/v1/ready | python3 -m json.tool
docker exec homehoard df -h /data
docker exec homehoard du -sh /data/homehoard.db /data/homehoard.db-wal /data/attachments 2>/dev/null
```

## 2. Reclaim space (safe, in order)
```bash
# a) A large WAL is normal but can be checkpointed back into the main DB:
docker exec homehoard python3 - <<'PY'
import sqlite3; c=sqlite3.connect('/data/homehoard.db'); print(c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
PY

# b) Host-side: prune old images/backups (NOT /data):
docker image prune -f
ls -1dt /backups/homehoard-* | tail -n +8 | xargs -r rm -rf   # keep newest 7

# c) If attachments dominate, move old backups offsite, then expand the volume.
```

## 3. Verify recovery
```bash
until curl -fsS http://127.0.0.1:7745/api/v1/ready; do sleep 2; done
docker exec homehoard df -h /data
```

## Prevention
- Alert when `/data` free space < 15% (see `docs/monitoring.md`).
- Keep backups on a **separate** volume/host from `/data`.
- SQLite WAL is auto-checkpointed; a persistently huge `-wal` implies a
  long-running reader — restart the app to release it.

**Abort:** if the DB became malformed from a mid-write ENOSPC, go to
`docs/runbooks/restore-failure.md`.
