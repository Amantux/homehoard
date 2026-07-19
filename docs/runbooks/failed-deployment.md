# Runbook: Failed deployment / bad release

**When:** a new image is unhealthy after deploy (`/ready` never 200, crash-loop,
or a regression in behavior).

## 1. Detect (the CI smoke gate should catch most before release)
```bash
docker inspect -f '{{.State.Health.Status}}' homehoard   # unhealthy?
until curl -fsS http://127.0.0.1:7745/api/v1/ready; do sleep 2; done   # hangs?
docker logs --tail 100 homehoard
```

## 2. Roll back to the previous known-good image (immutable tags)
```bash
# List available versions:
#   https://github.com/Amantux/homehoard/releases   (or GHCR tags)
PREV=1.0.2   # the last-good version
docker rm -f homehoard
docker run -d --name homehoard -p 7745:7745 \
  -e HBOX_SECRET_KEY -e HBOX_PROXY_HOPS=1 \
  -v homehoard-data:/data ghcr.io/amantux/homehoard:${PREV}
until curl -fsS http://127.0.0.1:7745/api/v1/ready; do sleep 2; done
```

Schema migrations are **additive only** (`_migrate` never drops/renames), so an
older image reads a newer DB safely. Still, if you're unsure, restore the
pre-deploy backup (`docs/runbooks/restore-failure.md`).

## 3. Prevent recurrence
- Confirm the CI `smoke` job ran for the bad commit (build → readiness → shutdown).
- Reproduce locally before re-releasing:
```bash
docker build -t homehoard:test .
docker run -d --name hh-test -p 7748:7745 -e HBOX_SECRET_KEY="$(openssl rand -base64 48)" homehoard:test
until curl -fsS http://127.0.0.1:7748/api/v1/ready; do sleep 2; done && echo OK
docker rm -f hh-test
```

## Record
Log what was deployed, when, by whom, and the version rolled back to (the GitHub
release + the commit SHA are the audit trail; CI records the built image digest).

**Abort/escalate** if rollback also fails readiness → the problem is data/config,
not the image → go to `container-wont-start.md`.
