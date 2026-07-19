# Architecture

Single-container application. Verified against the codebase — no external
datastores, brokers, queues, schedulers, or LLM providers exist.

## Service & dependency map

```
                    ┌──────────────────────── container (non-root uid 1000) ───────────────────────┐
   browser ──HTTP──▶│  gunicorn (2 sync workers) ──▶ Flask app  ──▶  SQLite (WAL) /data/homehoard.db │
   (SPA + API)      │        │  serves Vue SPA (frontend/dist)  ──▶  attachments /data/attachments/  │
                    │        └─ /api/v1/{status,ready,...}                                            │
   HA MCP Client ──▶│  uvicorn: MCP SSE server :7766  ──HTTP──▶ local Flask API (127.0.0.1:7745)     │
   (LLM Assist)     │        (optional Bearer token gate)                                            │
                    └──────────────────────────────────────────────────────────────────────────────┘
   HA Supervisor ──▶ add-on discovery (docker-entrypoint → /discovery)      Volume: /data (durable)
```

## Processes (the only "workers" — there is no queue system)

| Process | Command | Role | Health |
|---|---|---|---|
| gunicorn master + 2 workers | `gosu app gunicorn ... app:create_app()` | HTTP API + SPA | `/api/v1/ready` |
| MCP server | `gosu app python3 mcp_server.py` | HA LLM tool endpoint (SSE :7766) | TCP :7766 |
| entrypoint (one-shot) | schema init before workers | avoids create_all race | exits 0 |

There are **no** Celery workers, periodic schedulers, or message queues. HA-facing
"attention" data (warranties, maintenance) is computed on-demand in `/ha/summary`,
not by a background job.

## Data flows

- **Read/write inventory:** browser → gunicorn → SQLAlchemy → SQLite (parameterized).
- **Attachments:** upload → `secure_filename`+UUID → `/data/attachments`; download
  is `login_required`, group-scoped, `as_attachment=True`.
- **HA sensors/calendar:** HA integration polls `/ha/summary` + `/ha/calendar`.
- **HA voice/chat:** HA MCP Client → `:7766/sse` → MCP tools → local `/api/v1`.

## Failure domains

| Domain | Blast radius | Degradation |
|---|---|---|
| SQLite file corrupt/lost | total data loss without backup | `/ready` → 503; restore from backup |
| Disk full (`/data`) | writes fail | `/ready` storage check → 503 |
| Container down | full outage | restart; HEALTHCHECK-driven |
| MCP process down | HA voice/chat only | REST API + SPA unaffected (isolated process) |
| Rate-limit memory reset | limits reset on restart | benign (reconstructable) |

## Trust boundaries

- Browser ↔ API: JWT/API-token auth (unless `DISABLE_AUTH` behind HA ingress).
- API ↔ SQLite/FS: in-process, same container.
- HA LLM ↔ MCP `:7766`: **network-trust** by default; optional bearer token.
- Outbound notifiers (Apprise): SSRF-guarded (`_url_is_safe`).

See `docs/production-readiness.md` for what each boundary means per deployment tier.
