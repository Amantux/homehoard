# HomeHoard — Operability Build Plan

> This plan was created during a production-operability hardening pass. A generic
> operability brief assumed a Neo4j + Redis + Celery + LLM-fleet architecture;
> **HomeHoard is none of those.** Every assumption below is verified against the
> actual codebase (grep/tests/executed commands), and the plan is scoped to the
> real stack.

## Verified current state (evidence)

| Component | Reality | Evidence |
|---|---|---|
| API | Flask, served by **gunicorn** (2 sync workers, non-root) | `docker-entrypoint.sh`, `Dockerfile` |
| Frontend | Vue 3 SPA, built by Vite, served by Flask from `frontend/dist` | `backend/app/__init__.py` `_serve_spa` |
| Datastore | **SQLite** file at `$HBOX_DATA_DIR/homehoard.db` (WAL) | `config.py:67`, `extensions.py` pragmas |
| Object storage | Local files under `$HBOX_DATA_DIR/attachments/` | `config.py:attachments_dir` |
| Second process | **MCP server** (uvicorn, SSE `:7766`) for Home Assistant | `mcp_server.py`, `docker-entrypoint.sh` |
| Auth | JWT (72h) + long-lived API tokens; `DISABLE_AUTH` for HA ingress | `auth.py`, `api/tokens.py` |
| Rate limiting | Flask-Limiter, **in-memory** storage | `extensions.py` |
| Deploy | Multi-arch image → GHCR; GitHub release per version (HACS) | `.github/workflows/ci.yml` |

**Explicitly NOT present** (grep-verified, 0 matches): Neo4j/Cypher, Redis, Celery,
message broker, queues, periodic scheduler, LLM provider SDKs, CSP nonces,
idempotent-ingestion pipeline, fleet architecture. Sections of the original brief
about those are **Not Applicable** and marked so in `docs/production-readiness.md`.

## Failure domains (single-container app)

- **SQLite DB file** — single durable SPOF. No replication (embedded DB).
  Mitigation: WAL + `busy_timeout`, online backup + **executed** restore
  verification, `foreign_keys=ON`. HA requires external infra — see DR doc.
- **Attachments dir** — durable, on the same volume as the DB.
- **The container** — single instance. HA add-on / single Docker host model.
- **Rate-limit state** — in-memory, lost on restart (acceptable; reconstructable).
- **MCP endpoint** — unauthenticated by default (trusted-network model); optional
  `HBOX_MCP_SERVER_TOKEN` gate.

## Completed in this pass (all tested)

1. **Readiness vs liveness** — `/api/v1/ready` (DB + storage checks, 503 on
   failure) distinct from `/api/v1/status` (liveness). `test_operability.py`.
2. **SQLite durability** — WAL, `busy_timeout=5000`, `foreign_keys=ON` via a
   connect-event listener. Tested.
3. **Container HEALTHCHECK** — Docker-native, probes `/ready`. Verified `healthy`.
4. **Fresh-deploy crash fix** — schema init runs **once** in the entrypoint before
   workers, eliminating the multi-worker `create_all()` race that crash-looped a
   fresh container. Found by the new CI smoke gate.
5. **Backup + executed restore verification** — `scripts/backup.py` (online SQLite
   backup + attachments + manifest) and `scripts/restore_verify.py` (isolated
   restore, integrity checks, boots the app, count-match, report). Run in CI via
   `test_operability.py::test_backup_and_restore_verification_roundtrip`.
6. **CI smoke gate** — builds the image, waits for **readiness**, checks non-root
   + MCP port, confirms clean shutdown; gates the release.
7. **CI quality gates (prior pass)** — ruff+eslint lint, tests, add-on validation,
   plus an advisory security-scan workflow (CodeQL, pip-audit, npm audit, Trivy,
   gitleaks, SBOM). Config fail-closed on weak secrets.

## Remaining work (prioritized)

- **P1** Alerting rules doc + example Prometheus/Uptime-Kuma probes against
  `/ready` (monitoring is external; app exposes the signal). See `docs/monitoring.md`.
- **P2** Scheduled backups + offsite copy (currently on-demand script). Needs a
  storage target decision (S3/rsync) — infra choice.
- **P3** Optional Redis for rate-limit durability across workers/restarts — only
  if abuse observed. Documented, not implemented (adds a dependency).
- **P4** SQLite → Postgres path *if* multi-node/HA is ever required. Documented
  with tradeoffs; not needed at current scale.

## Risks / assumptions

- RPO/RTO in `docs/disaster-recovery.md` are **measured on a small dev DB**
  (0.9s restore) — real values scale with DB size; re-measure on prod-sized data.
- SLOs in `docs/production-readiness.md` are **proposed**, not measured (no
  production traffic baseline exists).
- The HA add-on path (Ingress, `/data/options.json`, Supervisor) is verified by
  container build/run but **not on a live Home Assistant** — pending.
