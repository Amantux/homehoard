# Production Readiness

Evidence-based, tiered. No single vague score — readiness depends on the
deployment context. "N/A" items are from a generic brief that assumed
infrastructure HomeHoard does not have (grep-verified).

## Readiness by deployment tier

### Tier A — internal / homelab / forgiving users → **READY**
Self-hosted single user or family. All blockers below are acceptable:
- Single SQLite / single container (no HA) — restore-from-backup covers loss.
- Proposed (not measured) SLOs — fine without an SLA.
- MCP unauthenticated on a trusted LAN.

**Do:** set a strong `HBOX_SECRET_KEY`, schedule `scripts/backup.py`, run
`restore_verify.py` monthly.

### Tier B — customer-facing / multi-tenant → **READY WITH CONDITIONS**
Blockers to close first:
- [ ] **Offsite, encrypted, scheduled backups** (today: on-demand, local). *(P2)*
- [ ] **External uptime monitoring** on `/api/v1/ready` + alerting. *(P1)*
- [ ] **TLS/HSTS reverse proxy** in front (app sets HSTS only when `is_secure`).
- [ ] Set `HBOX_MCP_SERVER_TOKEN` or firewall `:7766`.
- [ ] Set `HBOX_PROXY_HOPS` to the real proxy hop count.
- [ ] Measure real RTO on prod-sized data.

### Tier C — revenue / operations-critical → **NOT READY (by design at this scale)**
Requires infrastructure decisions HomeHoard intentionally avoids today:
- **No DB HA/replication** — SQLite is single-node. A restart or host loss is a
  brief full outage. HA needs SQLite→Postgres + managed/replicated DB. Concrete
  path + tradeoffs in `BUILD-PLAN.md` P4. **This is a blocker for Tier C only.**
- **Single container** — no rolling/zero-downtime deploy (documented interruption).
- **In-memory rate limiting** — not shared across replicas; needs Redis for HA.

## Checklist (with evidence)

| Control | State | Evidence |
|---|---|---|
| Readiness ≠ liveness | ✅ | `/api/v1/ready` vs `/status`; `test_operability.py` |
| Container healthcheck | ✅ | `Dockerfile HEALTHCHECK` → `healthy` (verified) |
| Fail-closed config | ✅ | default/weak secret refused; `test_security.py` |
| Non-root container | ✅ | pid1 uid=1000 (smoke) |
| CI gate (lint+test+smoke) | ✅ | `.github/workflows/ci.yml` |
| Security scanning | ✅ | CodeQL, pip-audit, Trivy, gitleaks, SBOM |
| Backup + **executed** restore verify | ✅ | `docs/disaster-recovery.md` |
| SQLite durability (WAL/FK/timeout) | ✅ | `extensions.py`; tested |
| Bounded outbound (SSRF guard) | ✅ | `_url_is_safe`; `test_security.py` |
| Rate limiting | ✅ (in-memory) | Flask-Limiter; per-worker (documented) |
| External monitoring/alerting | ⚠️ | app exposes `/ready`; wiring is operator-side |
| Offsite scheduled backups | ❌ | on-demand only (P2) |
| DB replication / HA | ❌ (N/A ≤ Tier B) | single SQLite |
| Zero-downtime deploy | ❌ | single container (documented) |
| Queue/scheduler/broker monitoring | **N/A** | none exist (grep-verified) |
| Neo4j / Redis / Celery / LLM fallback | **N/A** | none exist (grep-verified) |

## Proposed SLIs/SLOs (PROPOSED — no production baseline exists)

| SLI | Definition | Source | Proposed target | Data today? |
|---|---|---|---|---|
| Availability | `/ready` 200 ratio | external probe | 99.5% (Tier B) | not collected |
| API latency | p95 `/api/v1/items` | proxy/app logs | < 300ms | not collected |
| Error rate | 5xx / total | proxy logs | < 0.5% | not collected |
| Readiness freshness | probe interval | monitor | ≤ 60s stale | not collected |
| Backup freshness | now − last backup | backup manifest ts | ≤ 24h | manual |
| Restore success | `restore_verify` exit 0 | CI + cron | 100% | ✅ (CI) |

**Do not treat these as measured.** Instrument an external probe + proxy metrics
to collect real baselines before committing to targets.

## Known limitations (explicit)

- RTO/RPO numbers are **dev-scale**.
- HA add-on path verified by container build/run, **not on a live HA**.
- LLM "fallback" is N/A — HomeHoard doesn't call an LLM (it *serves* tools to HA's
  LLM via MCP). If an in-app LLM feature is ever added, add a provider abstraction
  then (interface + tests + telemetry), per the original brief.
