# HomeHoard

Home inventory & organization — a personal rewrite of
[homebox](https://github.com/hay-kot/homebox) with first-class Home Assistant
support, QR codes / barcodes, moving-box "bins", check in/out, and an **MCP
server** so Assist can answer *"where is my drill?"*.

![HomeHoard + Home Assistant MCP](https://raw.githubusercontent.com/Amantux/homehoard/main/docs/screenshots/mcp.png)

## Installation

1. Add this repository to the add-on store (or install directly if you found it
   via the HomeHoard repository).
2. Install **HomeHoard** and **Start** it.
3. Open it from the sidebar (Ingress) — no separate login needed.

![Dashboard](https://raw.githubusercontent.com/Amantux/homehoard/main/docs/screenshots/dashboard.png)

## Options

| Option | Default | Description |
|---|---|---|
| `disable_auth` | `true` | Skip in-app auth (Ingress already authenticates you). Set `false` for username/password login. |
| `allow_registration` | `false` | Allow creating new accounts (only relevant when auth is enabled). |
| `enable_mcp` | `true` | Run the MCP server (SSE on port `7766`) for the Home Assistant MCP Client. |
| `ollama_search_key` | `""` | Optional [Ollama](https://ollama.com) API key to look items up online and generate a short searchable description. Blank = off. |
| `barcode_lookup` | `false` | Identify an unknown scanned product barcode (UPC/EAN) online — product DB → Open Food Facts → Ollama web-search — to prefill a new item's name/brand. Off = scans still resolve your own QR tags and items, just no online product lookup. |
| `barcode_db_key` | `""` | Optional API key for the product-barcode DB. The default lookup endpoint is keyless — set this only if you've pointed the lookup at a keyed provider. |

Data (SQLite database + attachments) is stored under `/share/homehoard`.

## Highlights

- **Find where something is** — search items, bins, and locations with the full
  path (e.g. *Drill → Tool Shelf · Garage*).
- **Check in / out** — mark items *here* or *out* ("yes it's there, no it's
  not"), note who has them and a due date.
- **QR codes & product barcodes** — print HomeHoard QR labels or register your
  existing QR/UPC/EAN codes. Scanning (1D UPC/EAN and 2D QR/DataMatrix) resolves
  your own tags and items offline; with `barcode_lookup` on, an unknown product
  code is identified online to prefill a new item.
- **Bins** with photos; items inherit and follow their bin's location.

![Find where something is](https://raw.githubusercontent.com/Amantux/homehoard/main/docs/screenshots/search.png)

## Home Assistant integration

Install the **HomeHoard** HACS integration for one **HomeHoard** device with:

- **Sensors** — total items, total value, insured value, locations, bins,
  labels, warranties-expiring (30d), maintenance-overdue, and **checked-out**.
- **Binary sensor** — Online.
- **Calendar** — warranty expirations + scheduled maintenance.
- **Voice & chat** — ask *"where is my drill?"*, *"check out the drill"*. The
  easiest way is the **MCP server** below with an LLM Assist pipeline (no setup).
  A no-LLM option (plain Assist sentences) also ships — see the main README.
- **Service** — `homehoard.locate` for notifications / messaging (Telegram, …).

When this add-on is running, Home Assistant offers the integration automatically
via discovery ("New device found"). The add-on runs auth-disabled behind Ingress,
so it connects with no token. (Connecting a *standalone* HomeHoard with auth on?
Generate an **API token** in HomeHoard → **Home Assistant** and paste it into the
integration — see the README.)

## MCP server — the easy voice & chat path (Assist / LLMs)

This add-on also runs an **MCP server** (SSE on port **7766**, `/sse`) exposing
inventory tools to Home Assistant's **MCP Client**. The port is **not published to
your host/LAN** — it's reachable only on Home Assistant's internal network, so
HomeHoard stays entirely inside the HA boundary (UI/API via Ingress, MCP
internal-only). With an **LLM-powered** Assist conversation agent this is the
simplest way to talk to your inventory — full natural language, no sentence files.
Add it in **Settings → Devices & Services → Add Integration → Model Context
Protocol** using the add-on's internal container hostname (shown on the add-on's
info page):

```
http://<slug>-homehoard:7766/sse
```

Assist can then *find items, list checkouts, check things in/out, edit, and move*
by voice or chat. Disable with the `enable_mcp` option.
