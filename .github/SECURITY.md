# Security Policy

HomeHoard is a self-hosted Home Assistant add-on that runs on the operator's own
hardware behind Home Assistant, typically for a single household/admin.

## Supported versions

Only the latest published version receives security fixes. Please update the
add-on before reporting an issue.

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** — do not open a public
issue containing exploit details.

- Preferred: this repository's **Security** tab → **Report a vulnerability**
  (GitHub private advisory).
- If that is unavailable, open a minimal issue asking for a private contact and
  withhold specifics until we follow up.

Please include the affected version, a description, and reproduction steps or a
proof of concept. We aim to acknowledge within a few days.

## Scope notes

- Secrets (provider API keys, database URLs, MCP/provisioning tokens) live in the
  add-on configuration and the app database; add-on config access is trusted.
- The REST API and the MCP server are gated by per-client, revocable, **scoped**
  API keys (Full / REST / MCP) with a **Read-Only / Read-Write** access class.
  Any way to bypass those gates, or to reach mutating tools/endpoints with a
  read-only or wrong-scope key, is in scope.
