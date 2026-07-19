# Runbook: Container won't start / never becomes ready

**Symptom:** `docker ps` shows the container restarting, or `/api/v1/ready` never
returns 200, or the Docker healthcheck is `unhealthy`.

## 1. Confirm and classify
```bash
docker ps -a --filter name=homehoard
docker inspect -f '{{.State.Health.Status}} {{.State.ExitCode}}' homehoard
docker logs --tail 80 homehoard
```

## 2. Common causes (in order of likelihood)

**a) Missing/weak secret (fail-closed).** Log shows
`HBOX_SECRET_KEY is unset, a known default, or shorter than 32 characters`.
```bash
export HBOX_SECRET_KEY="$(openssl rand -base64 48)"   # then recreate the container
```

**b) `/data` not writable / disk full.** Log shows permission or `disk` errors,
or `/ready` returns `storage:error`. → `docs/runbooks/disk-full.md`.

**c) Corrupt database.** Log shows `sqlite3.DatabaseError: database disk image is
malformed`. → `docs/runbooks/restore-failure.md`.

**d) Port already in use.** `bind: address already in use` → free 7745 or remap.

## 3. Verify readiness (never trust "container up" alone)
```bash
until curl -fsS http://127.0.0.1:7745/api/v1/ready; do sleep 2; done
curl -s http://127.0.0.1:7745/api/v1/ready | python3 -m json.tool
```
A `503` with `database:error` or `storage:error` tells you which dependency is
the problem.

## 4. If still failing
Roll back to the last known-good image (`docs/runbooks/failed-deployment.md`) and
open an issue with `docker logs` + the `/ready` body attached.

**Abort condition:** if the DB is malformed and no recent backup exists, STOP and
escalate — do not delete `/data/homehoard.db`; copy it aside first
(`cp /data/homehoard.db /data/homehoard.db.corrupt-$(date +%s)`).
