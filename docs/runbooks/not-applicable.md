# Runbooks intentionally NOT written (infrastructure absent)

The originating operability brief listed runbooks for a Neo4j + Redis + Celery +
LLM-fleet system. HomeHoard has none of that infrastructure. These runbooks are
**not written because there is nothing to operate** — verified by grep across the
repo (0 matches):

| Requested runbook | Why N/A (evidence) |
|---|---|
| Queue has zero consumers | No message broker/queues (`celery`/`kombu`/`amqp`/`rabbitmq` → 0 matches). Work is synchronous in-request. |
| Queue backlog | Same — no queues. |
| Periodic job missed | No scheduler (`celery beat`/`apscheduler` → 0 matches). HA "attention" data is computed on-demand in `/ha/summary`. |
| Worker failure (consumer) | No async workers. The only processes are gunicorn workers (see `container-wont-start.md`) and the MCP server (`mcp-exposure.md`). |
| Redis outage | No Redis (`redis`/`sentinel` → 0 matches). Rate limiting is in-memory. |
| Neo4j outage | No Neo4j/Cypher (`neo4j`/`cypher`/`bolt://` → 0 matches). The DB is SQLite — see `restore-failure.md` / `disk-full.md`. |
| LLM provider outage | HomeHoard does not call an LLM. It *serves* tools to HA's LLM via MCP (`mcp-exposure.md`). No provider SDK (`openai`/`anthropic`/`langchain` → 0 matches). |

If any of these components is added later, add the corresponding runbook then.
The applicable runbooks are: `container-wont-start.md`, `restore-failure.md`,
`disk-full.md`, `failed-deployment.md`, `mcp-exposure.md`.
