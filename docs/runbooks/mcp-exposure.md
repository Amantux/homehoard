# Runbook: MCP endpoint exposure

**Concern:** the MCP server (`:7766/sse`) exposes inventory read + mutate tools
(`where_is`, `move_item`, `check_out_item`, …) to Home Assistant's LLM. By default
it is **unauthenticated** and relies on a trusted network. If `:7766` is reachable
from an untrusted network, anyone who can reach it can read and mutate inventory.

## 1. Check exposure
```bash
# Is 7766 published beyond the trusted network?
docker port homehoard 7766 2>/dev/null           # standalone: should NOT be public
# From an untrusted host, this should FAIL/timeout:
curl -m 3 http://<host>:7766/sse ; echo "exit=$?"
```
For the HA add-on, `7766` is **not published to the host** (no `ports:` entry in
`config.yaml`) — it is reachable only on the internal Supervisor network by the
add-on's container hostname. So the add-on is already internal-only by default;
`docker port` on the HA host shows nothing. The steps below apply to **standalone**
deployments (or if you manually add a `-p 7766:7766` mapping).

## 2. Remediate — require a token
```bash
# Set a token and recreate the container so the MCP endpoint requires it:
export HBOX_MCP_SERVER_TOKEN="$(openssl rand -base64 32)"
docker rm -f homehoard
docker run -d --name homehoard -p 7745:7745 \
  -e HBOX_SECRET_KEY -e HBOX_MCP_SERVER_TOKEN \
  -v homehoard-data:/data ghcr.io/amantux/homehoard:<version>
# Verify: no token → 401, correct token → 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7766/sse
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $HBOX_MCP_SERVER_TOKEN" http://127.0.0.1:7766/sse
```
Then set the same token in HA's MCP Client config. (Note: some HA MCP Client
versions can't send an auth header — if so, keep `:7766` firewalled to the HA
network instead of publishing it.)

## 3. Control exposure with the compose toggle (standalone)
`docker-compose.yml` publishes 7766 via `${HBOX_MCP_BIND:-127.0.0.1}:7766:7766`,
so exposure is a single `.env` variable — no file edits:

```bash
# Loopback only (default): reachable by an HA/MCP client on THIS host, not the LAN.
#   (leave HBOX_MCP_BIND unset)
# LAN-exposed: set BOTH of these in .env, then `docker compose up -d`
echo 'HBOX_MCP_BIND=0.0.0.0'                                  >> .env
echo "HBOX_MCP_SERVER_TOKEN=$(openssl rand -base64 32)"       >> .env
# Not running MCP at all:
echo 'HBOX_MCP_ENABLED=false'                                 >> .env
```

Verify after applying (`docker compose config | grep -A3 'target: 7766'` shows the
`host_ip`).

**Do not** expose `:7766` on the public Internet under any configuration.
