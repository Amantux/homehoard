# Monitoring

HomeHoard exposes health signals; the *monitoring backend is external* (the app
is a single container with no bundled metrics stack). This doc says what to watch
and how — with copy-pasteable probes.

## What the app exposes

| Signal | Endpoint / source | Meaning |
|---|---|---|
| Liveness | `GET /api/v1/status` → 200 | process is up |
| Readiness | `GET /api/v1/ready` → 200/503 | DB reachable **and** data dir writable; body has `dbLatencyMs` |
| Container health | Docker `HEALTHCHECK` (probes `/ready`) | `healthy`/`unhealthy` |
| Auth events | app log `homehoard.auth` | login ok/fail, unauthorized (audit) |
| MCP liveness | TCP `:7766` reachable | HA tool endpoint up |
| Backup freshness | `manifest.json.createdAt` | age of last backup |
| Restore success | `restore_verify.py` exit code | recoverability |

**Not applicable** (grep-verified absent): queue depth/age, consumer counts,
periodic-job freshness, broker/DLQ metrics, per-worker heartbeats through a
message bus. HomeHoard has no queues, broker, or scheduler — a "worker not
consuming its queue" alert has nothing to monitor.

## Minimal external monitoring (recommended)

Point any uptime monitor (Uptime Kuma, Blackbox exporter, healthchecks.io) at
readiness — **freshness-based**, not "process exists":

```yaml
# Blackbox-style HTTP probe
target: https://<host>/api/v1/ready
expect_status: 200
interval: 60s
# Alert if 2 consecutive probes fail OR status != 200 (a 503 = a dependency down).
```

Cron-report backup freshness (dead-man's-switch pattern):

```bash
# after each backup, ping a healthchecks.io check; alert fires if no ping in >24h
python3 scripts/backup.py --data-dir /data --out /backups/hh-$(date +%s) \
  && curl -fsS https://hc-ping.com/<uuid>
```

## Alerts (thresholds are INITIAL ASSUMPTIONS — tune with real data)

| Alert | Condition | Sev | Runbook |
|---|---|---|---|
| Not ready | `/ready` != 200 for ≥2 probes (≥2m) | critical | `runbooks/container-wont-start.md` (+ DB/disk) |
| DB slow | `dbLatencyMs` > 500 sustained | warning | `runbooks/disk-full.md` (often I/O/disk) |
| Disk full | `/ready` storage=error | critical | `runbooks/disk-full.md` |
| Backup stale | now − `createdAt` > 24h | warning | `runbooks/restore-failure.md` |
| Restore failing | `restore_verify` exit != 0 | critical | `runbooks/restore-failure.md` |
| MCP exposed | `:7766` reachable from untrusted net + no token | warning | `runbooks/mcp-exposure.md` |
| Auth brute force | spike in `login failed` logs / 429s | warning | rotate/limit; check `HBOX_PROXY_HOPS` |

Every alert should carry: what failed, environment, the current `/ready` body,
first diagnostic step, and a link to the runbook above. Use a 2-probe window to
avoid flapping; send a recovery notification when `/ready` returns to 200.

## Dashboards (suggested panels)

Availability (readiness success ratio) · p95 API latency (proxy) · 5xx rate ·
`dbLatencyMs` trend · backup age · last restore-verify result · MCP reachability.
Data sources are the reverse proxy logs + the external probe + the backup
manifest; wire these when a monitoring backend is chosen.
