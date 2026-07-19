# Disaster Recovery

HomeHoard's durable state is small and file-based. This doc is verified against
`scripts/backup.py` / `scripts/restore_verify.py`, both of which were **executed**
end-to-end (evidence below), not merely written.

## Backup inventory

| Item | Backed up | How | Classification |
|---|---|---|---|
| `homehoard.db` (SQLite) | ✅ | online `.backup()` (consistent under load, incl. WAL) | **durable** |
| `attachments/` (photos/docs) | ✅ | `attachments.tar.gz` | **durable** |
| `manifest.json` (checksums, counts) | ✅ | generated per backup | integrity metadata |
| Rate-limit state (Flask-Limiter) | ❌ | in-memory | **disposable / reconstructable** |
| Frontend build (`frontend/dist`) | ❌ | rebuilt from source | reconstructable |
| Secrets (`HBOX_SECRET_KEY`, tokens) | ❌ (by design) | see "Secrets" below | out of band |
| Deployment manifests | ✅ (in git) | `Dockerfile`, compose, workflows | versioned |
| Schema/migration state | ✅ (implicit) | schema lives in the DB; `_migrate` is additive | in-DB |

There is **no Redis / broker / Neo4j** to back up (verified absent).

## Frequency / retention / RPO / RTO

- **Frequency:** on-demand today (`scripts/backup.py`). Recommended: cron/systemd
  timer hourly or daily depending on tolerance. *(P2 — needs a storage target.)*
- **Retention:** operator-defined (keep last N backup dirs). Not yet automated.
- **Encryption:** backups are plaintext; encrypt at rest via the storage target
  (e.g. `age`, S3 SSE) — the DB may contain PII (serials, purchase prices).
- **RPO (recovery point):** = backup interval. With daily backups, ≤24h data loss.
- **RTO (recovery time):** **measured 0.9s** for a 6-item / 188 KB dev DB (see
  evidence). Scales with DB + attachment size; re-measure on prod-sized data.
- **Ownership:** the deploying operator (single-tenant self-host).

## Create a backup

```bash
# Against a running or stopped instance (online backup is safe while running):
python3 scripts/backup.py --data-dir /data --out /backups/homehoard-$(date +%Y%m%d-%H%M%S)
```

Produces `homehoard.db`, `attachments.tar.gz`, `manifest.json` in `--out`.

## Verify a backup is restorable (run this regularly — a backup you can't restore is not a backup)

```bash
python3 scripts/restore_verify.py --backup /backups/homehoard-<ts> --report restore-report.json
echo "exit=$?"   # 0 = PASS
cat restore-report.json
```

The verifier restores into an **isolated temp dir**, checks SHA-256 vs the
manifest, runs `PRAGMA integrity_check` + `quick_check`, boots the real app
against the restored data, confirms `/ready`, runs representative queries, checks
the restored item count matches the manifest, then cleans up. **It never writes to
the source or to any production system.**

### Executed evidence (dev DB)

```
Restore verification: PASS  (0.91s)
  [OK ] db_checksum                  sha256 matches manifest
  [OK ] attachments_checksum         sha256 matches manifest
  [OK ] integrity_check              ok
  [OK ] quick_check                  ok
  [OK ] schema_migrate               create_all + _migrate succeeded
  [OK ] readiness                    HTTP 200
  [OK ] items_query                  total=6
  [OK ] item_count_matches_backup    restored=6 manifest=6
  [OK ] locations_query              HTTP 200
  [OK ] search_query                 HTTP 200
  [OK ] read_is_stable               6 == 6
```

This same round trip runs in CI: `pytest tests/test_operability.py::test_backup_and_restore_verification_roundtrip`.

## Full restore into production (runbook)

See **`docs/runbooks/restore-failure.md`** for the step-by-step, including the
stop → restore → readiness-check → resume ordering and abort conditions.

## Secrets recovery

`HBOX_SECRET_KEY` and API tokens are **not** in backups. On restore with a *new*
secret, all existing JWT sessions are invalidated (users re-log in); API tokens
are stored hashed in the DB and survive a DB restore. Keep `HBOX_SECRET_KEY` in
your secret manager / `.env` outside the repo. See `docs/deployment.md`.

## Not yet verified (pending)

- Restore of a **prod-sized** DB (RTO/RPO numbers above are dev-scale).
- Restore on a live **Home Assistant add-on** (`/data` is Supervisor-managed).
- Offsite/immutable backup copy (currently local `--out` only).
