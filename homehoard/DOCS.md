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
| `mcp_expose_external` | `false` | Allow the MCP server to be reached from **outside** HA. Requires a minted MCP or Full API key (the server refuses to start without one; an MCP-scoped key is recommended) and mapping port `7766` in the Network tab. See "Reaching the MCP server from outside Home Assistant". |
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
- **Vault** — hide items behind a passphrase; they vanish from every list,
  search, total and notification until you unlock. See below.

![Find where something is](https://raw.githubusercontent.com/Amantux/homehoard/main/docs/screenshots/search.png)

## The vault (hidden items)

Mark an item **hidden** and it disappears from the whole add-on — listings,
search, counts, price totals, exports, HA sensors, notifications and anything
the assistant answers — until you unlock with a passphrase.

- **Set it up:** Items → **🔑 Set vault passphrase** (household owner only).
- **Hide:** select items → **Hide**, or tell the assistant "hide the telescope".
- **Unlock:** click **🔒 N hidden**, or say "unhide my items" and give the
  phrase. It stays open for that session until you lock it, you log out, or 12
  hours pass.

**Forgot the passphrase?** There is no recovery — it is stored only as a hash.
You can reset the vault, which **permanently deletes everything inside it**:
`POST /api/v1/vault/reset` previews a count, and `{"confirm": true}` performs it.
It deletes rather than simply re-keying on purpose: if an owner could re-key
their way in, the passphrase would protect nothing from the people most likely
to look.

**What it is not:** encryption. Hidden rows are plaintext in the database, so
anyone with the database file, a backup, or an admin token can read them
whatever the lock state. If you unlock via chat, the passphrase reaches your
configured LLM provider and stays in chat history — unlock from the UI if that
matters.

## AI features

Wire up any LLM or local SLM once in **Tools → AI provider**, then it powers
everything below. Choose **Ollama** (self-hosted), **Ollama Cloud** (ollama.com —
paste your API key, then *List models* to pick one), **OpenAI-compatible** — point
the base URL at a local model server such as LM Studio, vLLM, llama.cpp, or Ollama's
`/v1` — or **Anthropic Claude**. Everything runs against *your* provider; nothing is
sent anywhere else.

- **Assistant (chat)** — ask where things are, what's in a location, or to tag an
  item. It answers by looking up your own inventory.
- **AI descriptions** — *Tools → AI descriptions* looks items up online and stores a
  short searchable description, so search finds them by what they actually are. Runs
  in the background with a progress bar (needs an ollama.com web-search key).
- **AI organize** — *Tools → AI organize*:
  - **Auto-categorize** proposes a label per unlabeled item. Confident matches to an
    existing label apply automatically; anything less certain waits for you.
  - **Propose groupings** suggests named collections ("Camping gear", "Kids winter
    clothes").
  - Review pending suggestions in **Review** (accept/reject). Your choices are fed
    back as examples, so later runs match your preferences. Optionally add a *note*
    or pick a specific *model* per run.

Provider config is instance-wide and editable only by the founding household's owner.

## Actionable notifications

Set **public_url** (Configuration tab) to the URL you open HomeHoard at, and
every notification digest gains tap-through links straight to the Restock,
Checked-out and Maintenance pages.

For real buttons, pair the digest with a Home Assistant actionable
notification — the add-on provides the data and the REST endpoints, HA provides
the buttons. Example: a daily digest with a "Show restock list" action:

```yaml
automation:
  - alias: HomeHoard daily digest
    trigger: [{ platform: time, at: "08:00:00" }]
    action:
      - service: rest_command.homehoard_dispatch     # POST /api/v1/notifiers/dispatch
      - service: notify.mobile_app_your_phone
        data:
          message: "HomeHoard has updates"
          data:
            actions:
              - action: URI
                title: "Show restock list"
                uri: "/api/hassio_ingress/YOUR_TOKEN/#/restock"
```

"Mark maintenance done" works the same way: an action that fires a
`rest_command` at `PUT /api/v1/items/<item_id>/maintenance/<entry_id>` with
`{"completedDate": "..."}`.

## Home Assistant integration

Install the **HomeHoard** HACS integration for one **HomeHoard** device with:

- **Sensors** — total items, total value, insured value, locations, bins,
  labels, warranties-expiring (30d), maintenance-overdue, and **checked-out**.
- **Binary sensor** — Online.
- **Calendar** — warranty expirations + scheduled maintenance.
- **To-do list** — the restock (shopping) list as a native HA to-do list
  (*"AA batteries — buy 11"*), same suggestions as the app's Restock page.
  Checking an item off means "I bought it" and only hides it from the list —
  it never silently changes inventory. Record the new quantity in HomeHoard
  and the item leaves the restock feed for real; if you don't, it reappears
  on a later refresh while the inventory still says it's low.
- **Voice & chat** — ask *"where is my drill?"*, *"check out the drill"*. The
  easiest way is the **MCP server** below with an LLM Assist pipeline (no setup).
  A no-LLM option (plain Assist sentences) also ships in **English, German,
  Spanish, French and Dutch** — depending on your setup the sentence file for
  your language may need a one-time copy into your HA config's
  `custom_sentences/<lang>/` directory; see the main README.
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

### Reaching the MCP server from OUTSIDE Home Assistant

By default the MCP server is internal-only and **unauthenticated** (safe because it
isn't reachable from your host/LAN). To connect an external MCP client (e.g. Claude
Desktop, another agent) you must turn on authentication **and** publish the port —
both, in this order:

1. **Mint an MCP key.** In HomeHoard → **Home Assistant → API tokens**, generate a
   token with **Scope = MCP only**. Copy it (shown once). MCP keys are rejected by
   the REST API, so they only grant MCP access, and you can revoke one client without
   touching the others. Set **Access = Read only** to give a client that can query
   inventory but cannot move/check-out/edit anything (read-only keys are also limited
   to GET on the REST API); leave it **Read & write** for a full client.
2. **Turn on `mcp_expose_external`** in the add-on **Configuration**. With this on,
   every MCP request must carry a valid MCP (or Full) key, and the MCP server
   **refuses to start** until at least one MCP or Full key exists — so it can never
   come up open. An MCP-scoped key is recommended (it can't touch the REST API).
   Restart the add-on after minting the key.
3. **Publish the port.** In the add-on's **Network** tab, map container port `7766`
   to a host port. Point your client at `http://<your-ha-host>:<mapped-port>/sse`
   with header `Authorization: Bearer <your MCP key>`.

⚠️ Anything reachable over MCP includes **mutating** tools (move/check-in/out/edit).
The bearer key is the only control — put it behind TLS (a reverse proxy) if you
expose it beyond your LAN, and revoke the key in the token list if it leaks.
