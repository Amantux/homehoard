# Runbook: Restore failure / database corruption

**When:** the DB is corrupt/lost, or `scripts/restore_verify.py` exits non-zero,
or you need to recover onto a fresh host.

## 0. Do no harm
```bash
# Never overwrite the current DB until you have a verified good backup restored.
cp /data/homehoard.db /data/homehoard.db.bad-$(date +%s) 2>/dev/null || true
```

## 1. Pick a backup and VERIFY it before trusting it
```bash
ls -1dt /backups/homehoard-*        # newest first
python3 scripts/restore_verify.py --backup /backups/homehoard-<ts> --report /tmp/rv.json
echo "exit=$?"                       # must be 0
python3 -m json.tool /tmp/rv.json    # every check ok:true
```
If verification FAILS, try the next-older backup. A failing `integrity_check`
means that artifact is corrupt — do not restore it.

## 2. Restore into a stopped instance
```bash
docker stop homehoard                       # take the app down (brief outage)
# Restore DB + attachments from the verified backup:
cp /backups/homehoard-<ts>/homehoard.db /data/homehoard.db
rm -f /data/homehoard.db-wal /data/homehoard.db-shm   # stale WAL from the bad DB
mkdir -p /data/attachments
tar -xzf /backups/homehoard-<ts>/attachments.tar.gz -C /data/attachments
chown -R 1000:1000 /data                    # app runs as uid 1000
```

## 3. Start and confirm READINESS (not just "up")
```bash
docker start homehoard
until curl -fsS http://127.0.0.1:7745/api/v1/ready; do sleep 2; done
curl -s http://127.0.0.1:7745/api/v1/ready         # ready:true, database:ok, storage:ok
# Spot-check data:
curl -s "http://127.0.0.1:7745/api/v1/status"
```

## 4. Validate integrity in place
```bash
docker exec homehoard python3 - <<'PY'
import sqlite3; print(sqlite3.connect('/data/homehoard.db').execute('PRAGMA integrity_check').fetchone()[0])
PY
```

## Expectations & abort
- **Data loss:** everything written since the chosen backup (= your RPO).
- **Duration (RTO):** seconds for small DBs; re-measure for large ones.
- **Background jobs:** none exist — nothing to resume; API tokens survive (stored
  hashed in the DB).
- **Abort** if no backup passes `restore_verify` — escalate; keep the corrupt DB
  copy for forensic recovery (`.recover` may salvage rows) rather than deleting it.
