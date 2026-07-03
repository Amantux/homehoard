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

Data (SQLite database + attachments) is stored under `/share/homehoard`.

## Highlights

- **Find where something is** — search items, bins, and locations with the full
  path (e.g. *Drill → Tool Shelf · Garage*).
- **Check in / out** — mark items *here* or *out* ("yes it's there, no it's
  not"), note who has them and a due date.
- **QR codes & your own barcodes** — print HomeHoard QR labels or register your
  existing QR/UPC/EAN codes; scanning is inventory-only (no outbound calls).
- **Bins** with photos; items inherit and follow their bin's location.

![Find where something is](https://raw.githubusercontent.com/Amantux/homehoard/main/docs/screenshots/search.png)

## Home Assistant integration

Install the **HomeHoard** HACS integration for one **HomeHoard** device with:

- **Sensors** — total items, total value, insured value, locations, bins,
  labels, warranties-expiring (30d), maintenance-overdue, and **checked-out**.
- **Binary sensor** — Online.
- **Calendar** — warranty expirations + scheduled maintenance.
- **Voice** — *"where is my drill?"* (copy the shipped `custom_sentences` file).
- **Service** — `homehoard.locate` for notifications / messaging (Telegram, …).

When this add-on is running, Home Assistant offers the integration automatically
via discovery ("New device found").

## MCP server (Assist / LLMs)

This add-on also runs an **MCP server** (SSE on port **7766**, `/sse`) exposing
10 inventory tools. Add it in **Settings → Devices & Services → Add Integration
→ Model Context Protocol** with URL:

```
http://<this-host>:7766/sse
```

Assist can then *find items, list checkouts, and check things in/out* by voice
or chat. Disable with the `enable_mcp` option.
