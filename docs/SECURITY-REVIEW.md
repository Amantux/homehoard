# HomeHoard — Security Assessment

> Scope: Flask API + Vue SPA + Home Assistant integration + in-container MCP server.
> Self-hosted (Docker / HA add-on), intended for eventual public-internet exposure.
> Method: code-level review of every blueprint, the auth layer, models/serializers,
> MCP tools, Docker/compose/CI, and dependencies. Findings cite files/lines.
> Low-confidence items are marked **Needs Manual Validation**.

_Status column tracks remediation. See `CHANGELOG.md` / git history for the fixes._

## Executive summary

HomeHoard has solid fundamentals for a self-hosted app: 100% ORM-parameterized
queries (no SQLi), consistent per-group tenant scoping, bcrypt password hashing,
hashed + revocable API tokens, `secure_filename`+UUID upload naming, and no
dangerous sinks (`eval`/`pickle`/`subprocess`). CSRF is largely N/A because auth
is `Authorization`-header based, not cookies.

The dominant risk theme is **"secure only behind a trusted network boundary."**
That assumption is baked in (`DISABLE_AUTH`, an unauthenticated MCP server, no
rate limiting) and breaks on public exposure. The most dangerous single issue is
a predictable default JWT signing secret shipped in `docker-compose.yml`.

Counts: **1 Critical · 3 High · 8 Medium · 8 Low · 5 Informational.**

## Findings

| ID | Sev | Title | OWASP / CWE | Status |
|----|-----|-------|-------------|--------|
| C1 | Critical | Predictable default JWT signing secret → token forgery | A02 / CWE-798,321 | Fixed (fail-closed) |
| H1 | High | SSRF via notifier (Apprise) URLs | A10,API7 / CWE-918 | Fixed (allowlist + private-range block) |
| H2 | High | MCP server exposes mutating tools with no auth | API2 / CWE-306 | Fixed (optional bearer token) |
| H3 | High | No rate limiting + user enumeration (brute force) | A07,API4 / CWE-307,204 | Fixed (Flask-Limiter + constant-time login) |
| M1 | Medium | No security headers (CSP, XFO, HSTS, nosniff) | A05 / CWE-693,1021 | Fixed |
| M2 | Medium | JWT in localStorage, no revocation, 7-day life | A07 / CWE-522,613 | Partial (shorter expiry, iat; revocation = roadmap) |
| M3 | Medium | Stored file served inline → stored XSS in group | A05 / CWE-79,434 | Fixed (as_attachment + nosniff) |
| M4 | Medium | CSV formula injection on export | / CWE-1236 | Fixed |
| M5 | Medium | Unbounded pagination / full-table dump | API4 / CWE-770,400 | Fixed (clamped) |
| M6 | Medium | Invitation uses/expiry not enforced | / CWE-840 | Fixed |
| M7 | Medium | CORS reflects any origin w/ credentials | A05 / CWE-942 | Fixed (allowlist) + dep bump |
| M8 | Medium | Indirect prompt injection via inventory text into MCP/LLM | LLM01/07 | Partial (minimal tool set, guidance, audit log) |
| L1 | Low | Notifier IDOR within a group | / CWE-639 | Fixed (user-scoped) |
| L2 | Low | Weak password policy / no MFA | / CWE-521 | Partial (min length; MFA = roadmap) |
| L3 | Low | `update_self` email change w/o uniqueness | / CWE-708 | Fixed |
| L4 | Low | Container runs as root | / CWE-250 | Fixed (non-root USER) |
| L5 | Low | Dependency hygiene (flask-cors, gunicorn, no scanning) | / CWE-1104,1035 | Fixed (bumps + Dependabot) |
| L6 | Low | `get_json(force=True)` ignores Content-Type | | Accepted (no cookie auth → no CSRF) |
| L7 | Low | Race conditions (asset_id, checkout, token last_used) | / CWE-362 | Accepted (single-writer home app) |
| L8 | Low | `/qrcode` unbounded input DoS | / CWE-400 | Fixed (length cap) |
| I1 | Info | `DISABLE_AUTH` = total bypass if exposed | | Startup warning added |
| I2 | Info | No audit logging | | Auth events now logged |
| I3 | Info | No secret-rotation story | | Documented |
| I4 | Info | PII unencrypted at rest | | Documented (self-host) |
| I5 | Info | `data/*.db`/`*.log` in working tree | | Confirmed gitignored |

## Threat model (STRIDE)

- **Assets:** inventory PII (names/photos/serials/prices), credentials, JWT
  signing key, notifier webhook secrets, the SQLite DB, on-disk attachments.
- **Actors:** unauthenticated Internet attacker; low-priv authenticated user
  (open registration); malicious same-group member; a poisoned LLM Assist agent;
  a LAN/Supervisor-network attacker.
- **Trust boundaries:** browser↔API; API↔SQLite/FS; API↔outbound notifiers
  (SSRF crossing); HA LLM↔MCP (was unauthenticated); `DISABLE_AUTH` collapses
  browser↔API entirely.
- **Entry points:** `/api/v1/*`, the SPA, the MCP SSE endpoint (`:7766`), CSV
  import, file uploads, notifier URLs.

| STRIDE | Manifestation |
|--------|---------------|
| Spoofing | Forgeable JWTs (C1); no MCP auth (H2) |
| Tampering | Same-group notifier IDOR (L1); MCP mutating tools (H2) |
| Repudiation | No audit logging (I2) |
| Information disclosure | Unbounded pagination (M5); enumeration (H3); SSRF (H1) |
| Denial of service | No rate limiting (H3); `pageSize=0` (M5); `/qrcode` (L8) |
| Elevation | Default-secret forgery (C1); `DISABLE_AUTH` if exposed (I1) |

## What is already good (do not regress)

- All DB access via SQLAlchemy ORM with bound parameters — no SQL injection.
- Tenant scoping is consistent: every `_get` validates
  `group_id == current_group().id`; list queries filter by group.
- API tokens are SHA-256 hashed, `hh_`-prefixed, revocable, IDOR-tested.
- Uploads use `secure_filename` + a UUID prefix — no upload path traversal.
- Passwords hashed with bcrypt.
- No `eval`/`exec`/`pickle`/`subprocess`/`os.system`.
- CI uses a least-privilege `permissions:` block.

## Residual risk / roadmap

- **M2 (token model):** full revocation and moving off `localStorage`
  (refresh-token rotation or httpOnly-cookie + CSRF) is a larger change; only
  expiry shortening + `iat` shipped here.
- **M8 (LLM):** indirect prompt injection is inherent to feeding user data to an
  LLM; mitigated by a minimal, non-destructive tool set and invocation logging,
  not eliminated.
- **L2 (MFA), L7 (row-level locking), at-rest encryption, a hardened
  TLS/HSTS/WAF reverse-proxy reference** remain roadmap items.
- **H1 residual (DNS rebinding / redirects):** `_url_is_safe` validates the
  resolved IP at save/test time, but Apprise re-resolves and follows redirects
  when it actually sends, so a rebinding or redirect-to-internal attack is not
  fully closed. Full mitigation needs a pinned-IP resolver / egress firewall.
- **H3 residual (limiter storage):** the rate limiter uses in-memory storage,
  so limits are per-gunicorn-worker (currently 2) and reset on restart. For a
  hard global limit, point `RATELIMIT_STORAGE_URI` at Redis.
- **M2 residual (JWT on restart):** the container generates a random
  `HBOX_SECRET_KEY` when none is provided, so all sessions are invalidated on
  restart. Set a persistent secret to keep sessions across restarts.

## Deployment guidance (public exposure)

1. Set a strong `HBOX_SECRET_KEY` (≥32 random bytes). The app refuses to boot
   with a known default when auth is enabled.
2. Terminate TLS at a reverse proxy; set `HBOX_PROXY_HOPS` to the number of
   trusted proxies so rate limiting keys on the real client IP.
3. Restrict `HBOX_CORS_ORIGINS` to your frontend origin(s) if the SPA is hosted
   separately; leave unset for same-origin.
4. Set `HBOX_MCP_SERVER_TOKEN` and do not publish port `7766` beyond the HA
   network.
5. Keep `HBOX_DISABLE_AUTH=false` unless strictly behind HA ingress / a trusted
   authenticating proxy.

## Security maturity: 48/100 (pre-remediation)

Strong data-layer safety and code hygiene, but production-exposure controls
(secret management, rate limiting, SSRF defense, MCP auth, headers, dependency
scanning) were largely absent. The remediation batch in this repo targets the
Critical/High/Medium set; re-scoring after those lands is expected in the ~80s.
