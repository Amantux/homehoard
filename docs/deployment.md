# Deployment

HomeHoard deploys as one immutable container image, built and released by CI.

## Pipeline (`.github/workflows/ci.yml`)

On every push to `main` (gating jobs must pass before release):

1. **backend-tests** — pytest (86 tests incl. security + operability + DR round trip).
2. **frontend-build** — `npm ci && npm run build`.
3. **lint** — ruff + eslint.
4. **validate-addon** — `config.yaml`/`manifest.json` shape + version lockstep.
5. **smoke** — build the image, run it, **wait for `/api/v1/ready`**, assert
   non-root + MCP listening, confirm clean shutdown.
6. **bump-version** → **docker-build (amd64+arm64)** → **merge-manifest** →
   **release** (GitHub release for HACS; image `ghcr.io/amantux/homehoard:<ver>`).

**Blocking vs advisory:** jobs 1–5 block the release. The separate
`security-scan` workflow (CodeQL, pip-audit, npm audit, Trivy, gitleaks, SBOM) is
**advisory** — results go to the Security tab; it never blocks a release, so an
upstream CVE can't wedge the pipeline.

## Configuration model

| Layer | Where | Notes |
|---|---|---|
| Safe defaults | `backend/app/config.py` | e.g. WAL, 72h JWT, min-password 8 |
| Dev | `python run.py` / vite proxy | set `HBOX_DISABLE_AUTH=1` or a secret |
| Test | `tests/conftest.py` | rate limit off, fixed secret |
| Prod (standalone) | env vars / `.env` (git-ignored) | `docker-compose.yml` |
| Prod (HA add-on) | `/data/options.json` → env | `homehoard/config.yaml` schema |
| Secrets | env / secret manager | **never** in git |

Required in production (auth enabled): **`HBOX_SECRET_KEY`** (≥32 random bytes —
the app refuses to boot otherwise). Recommended: `HBOX_PROXY_HOPS`, optionally
`HBOX_CORS_ORIGINS`.

**MCP exposure (standalone):** the HA add-on keeps MCP internal (no host port).
For standalone compose it's toggleable via `.env`:

| Goal | Set in `.env` |
|---|---|
| Loopback only (default — HA/MCP client on the same host) | *(nothing)* |
| Exposed to the LAN (HA on another host) | `HBOX_MCP_BIND=0.0.0.0` **and** `HBOX_MCP_SERVER_TOKEN=<token>` |
| Don't run MCP at all | `HBOX_MCP_ENABLED=false` |

There is **no `.env.local` as production source of truth** and **no second repo
clone** in the deploy path — the image is self-contained.

## Deploy a specific version (standalone)

```bash
export HBOX_SECRET_KEY="$(openssl rand -base64 48)"   # once; keep it stable
docker pull ghcr.io/amantux/homehoard:1.0.3
docker rm -f homehoard 2>/dev/null || true
docker run -d --name homehoard -p 7745:7745 \
  -e HBOX_SECRET_KEY -e HBOX_PROXY_HOPS=1 \
  -v homehoard-data:/data ghcr.io/amantux/homehoard:1.0.3
# Wait for readiness (not just "started"):
until curl -fsS http://127.0.0.1:7745/api/v1/ready; do sleep 2; done
```

## Rollback

Immutable tags make rollback a re-pull of the prior version:

```bash
docker rm -f homehoard
docker run -d --name homehoard -p 7745:7745 -e HBOX_SECRET_KEY \
  -v homehoard-data:/data ghcr.io/amantux/homehoard:<previous-version>
until curl -fsS http://127.0.0.1:7745/api/v1/ready; do sleep 2; done
```

Schema migrations are **additive** (`_migrate` only ADDs columns/tables), so an
older image reads a newer DB safely. Take a backup before any upgrade regardless
(`scripts/backup.py`). See `docs/runbooks/failed-deployment.md`.

## Downtime expectation

Single container ⇒ a restart is a brief (seconds) full outage — controlled and
observable via `/ready`. Zero-downtime needs multiple replicas + shared state
(not in scope at current scale).
