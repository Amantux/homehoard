# HomeHoard 📦

**HomeHoard is my own personal rewrite of [homebox](https://github.com/hay-kot/homebox).**

I love what homebox does, but I wanted three things it didn't give me, so I
rebuilt it from the ground up in Python:

1. **Home Assistant, done properly.** HomeHoard runs as a first-class HA **add-on**
   (one-click install, Ingress, no separate login) and ships a companion
   **HACS integration** with inventory **sensors**, a warranties/maintenance
   **calendar**, a **voice intent** ("where is my drill?"), a `homehoard.locate`
   **service** for notifications/messaging, and an in-container **MCP server** so
   an LLM-powered Assist can search and check items in/out.
2. **QR codes and barcodes that actually fit my life.** Generate printable QR
   labels *and* register your **own** existing QR labels or product barcodes
   (UPC/EAN), stick as many codes as you like on a single bin, and scan any of
   them from your phone to jump straight to the record.
3. **Planning my upcoming move.** I needed **bins** — pack a bin, label it, and
   know exactly what's inside every box and which room it belongs to. Moving a
   bin to a new room moves everything inside it with it.

It's a faithful reimplementation of homebox's data model (aligned with the
maintained [sysadminsmedia/homebox](https://github.com/sysadminsmedia/homebox)
fork) with a **Flask + SQLAlchemy** backend and a **Vue 3 (Vite)** SPA, packaged
to run as a standalone Docker container, a Home Assistant add-on, or on a
Raspberry Pi 5.

> HomeHoard stands on the shoulders of homebox and, like homebox, is licensed
> under **AGPL-3.0**. Huge thanks to [@hay-kot](https://github.com/hay-kot) and
> the homebox community.

## 🏆 The headline: ask Home Assistant where your stuff is

HomeHoard exposes your whole inventory to Home Assistant through an **MCP server
that runs inside the same add-on container** — so an LLM-powered Assist can
answer *"where is my drill?"* and even check tools in and out, by voice or chat.

![HomeHoard MCP integration with Home Assistant Assist](docs/screenshots/mcp.png)

## 📸 Screenshots

| Dashboard | Find where something is |
|---|---|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Search](docs/screenshots/search.png) |
| **Item detail — checked out** | **QR codes & barcodes** |
| ![Item detail](docs/screenshots/item-detail.png) | ![QR codes](docs/screenshots/qr-codes.png) |
| **Bins** | **Items grid** |
| ![Bin detail](docs/screenshots/bin-detail.png) | ![Items](docs/screenshots/items.png) |

## ✨ What's new

- **🤖 MCP server for Home Assistant** — 10 inventory tools (`where_is`,
  `check_out_item`, `list_checkouts`, …) over SSE, in the same container.
- **🔎 "Where is it?" search** across items, bins, and locations, with full
  location paths — in the app, by **voice** ("where is my drill?"), and via the
  `homehoard.locate` service for **notifications/messaging**.
- **📥 Check in / out** — "yes it's here / no it's not," with who has it, a due
  date, overdue flags, and history.
- **📷 Inventory-only scanning** — scan your **own** QR labels and product
  barcodes; no outbound calls. Known code → the record (or a bin/location's
  contents); unknown → create or link on the spot.
- **🗃️ Bins** with photos, plus items that inherit (and follow) their bin's
  location.
- **🩺 HA sensors + calendar** — totals, insured value, checked-out count,
  warranties-expiring, maintenance-overdue, and a warranties/maintenance
  **calendar**.
- **🚀 Reliable CI** — native amd64 + **arm64 (Raspberry Pi 5)** images, merged
  into a multi-arch manifest and auto-versioned on every push.

## 🗺️ Roadmap

- Voice **"what's in the garage?"** (speak a bin/location's contents)
- **Consumables / low-stock** thresholds → a to-do / shopping list entity
- **Scan-to-checkout** ("scan → check out to me") and richer QR label sheets
- Multi-language Assist sentences
- Actionable notifications ("Reorder" / "Mark maintenance done")


## Home Assistant

HomeHoard ships with **both** halves of a proper Home Assistant integration — a
Supervisor **add-on** (the app itself, via Ingress) and a **HACS integration**
(inventory sensors). Set it up in three clicks:

### Step 1 — Add the Supervisor repository

[![Add repository to Home Assistant Supervisor](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FAmantux%2Fhomehoard)

Or manually: **Settings → Add-ons → Add-on Store → ⋮ → Repositories** → paste
`https://github.com/Amantux/homehoard`

### Step 2 — Add the integration via HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Amantux&repository=homehoard&category=integration)

Or manually in HACS: **Integrations → ⋮ → Custom repositories** → paste
`https://github.com/Amantux/homehoard` → category **Integration** → **Add**.

### Step 3 — Start the add-on, watch it appear automatically

Install **HomeHoard** from the add-on store, then **Start** it. Within seconds a
**New device found** card will appear in **Settings → Devices & Services** — no
manual configuration needed.

[![Start setting up HomeHoard integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=homehoard)

The add-on opens from the sidebar (Ingress, no separate login), stores data in
`/share/homehoard`, and builds for **aarch64** (Raspberry Pi 5) and amd64.

#### What the integration gives you

The companion integration (`custom_components/homehoard`) polls a consolidated
`/api/v1/ha/summary` endpoint and creates one **HomeHoard** device with:

- **Sensors** — total items, total value, insured value, locations, bins,
  labels, **warranties expiring (30d)** (with a 90-day + item list attribute),
  and **maintenance overdue** (with upcoming + entries attribute).
- **Binary sensor** — `Online` (connectivity to the HomeHoard instance).
- **Calendar** — *Warranties & maintenance*: every warranty-expiry and scheduled
  maintenance date as calendar events, so you can automate reminders
  ("notify me 30 days before any warranty expires").

#### Find things by voice & messaging

The integration wires HomeHoard's search into Home Assistant so you can ask
**"where is my drill?"** — it answers with the location (e.g. *"Drill is in Tool
Bin · Garage › Shelf."*). Search matches **items, bins, and locations**.

- **Voice (Assist):** copy
  `custom_components/homehoard/custom_sentences/en/homehoard.yaml` to
  `<your HA config>/custom_sentences/en/homehoard.yaml` and restart HA. Then say
  *"where is my …"*, *"find the …"*, *"which bin has the …"*.
- **Service / messaging:** call **`homehoard.locate`** (a response service) from
  any automation or script — great for Telegram/notify bots:

  ```yaml
  # Reply to a Telegram message like "where is my passport"
  - alias: HomeHoard locate over Telegram
    trigger:
      - platform: event
        event_type: telegram_text
    action:
      - service: homehoard.locate
        data:
          query: "{{ trigger.event.data.text }}"
        response_variable: found
      - service: telegram_bot.send_message
        data:
          message: "{{ found.speech }}"
  ```

  `homehoard.locate` returns `{ speech, results[] }`, where each result has
  `type` (item/bin/location), `name`, `where`, and (for bins/locations) `count`.

#### MCP server (for Assist / LLMs)

HomeHoard ships an **MCP server** that runs **in the same container** (no extra
service) and exposes inventory tools to Home Assistant's **MCP Client**
integration — so an LLM-powered Assist can call them directly:

`where_is`, `search_inventory`, `get_item`, `get_bin_contents`,
`get_location_contents`, `list_checkouts`, `check_out_item`, `check_in_item`,
`create_item`, `inventory_statistics`.

- It's served over **SSE on port `7766`** (`/sse`), enabled by default (add-on
  option `enable_mcp`).
- In Home Assistant: **Settings → Devices & Services → Add Integration → Model
  Context Protocol**, and point it at
  `http://<homehoard-host>:7766/sse`
  (e.g. your HA host's IP, since the add-on maps port 7766). Assist can then
  answer *"where is my drill?"* and check items in/out via the MCP tools.
- Standalone (outside HA): `python backend/mcp_server.py`
  (`HBOX_MCP_API` points it at the app's API; defaults to `http://127.0.0.1:7745/api/v1`).

Example automation:

```yaml
automation:
  - alias: HomeHoard warranty warning
    trigger:
      - platform: numeric_state
        entity_id: sensor.homehoard_warranties_expiring_30d
        above: 0
    action:
      - service: notify.notify
        data:
          title: HomeHoard
          message: >-
            {{ states('sensor.homehoard_warranties_expiring_30d') }} warranty(s)
            expiring within 30 days.
```


## Features

- Items with quantity (fractional), purchase/warranty/sold details, custom
  fields (text/number/boolean/**time**), notes — field set aligned with the
  maintained [sysadminsmedia/homebox](https://github.com/sysadminsmedia/homebox) fork
- Nested **locations** (tree) and **labels/tags** (color, icon, hierarchy)
- **Bins**: a location holds bins, and each bin holds a collection of items.
  Items can sit directly in a location or inside a bin.
- **Multiple QR codes per item, bin, or location** — stick several printed
  codes on one physical object; scanning any of them opens that record. QR
  images and print-ready pages included.
- **Check in / out** — mark an item as *here* or *checked out* ("yes it's there,
  no it's not"), optionally noting who has it and a due date. `/checkouts` lists
  everything currently out (with overdue flags); a *Checked out* HA sensor tracks
  the count.
- **"Where is it?" search** — a spotlight-style search (top bar or the `/` key)
  matching **items, bins, and locations** and showing the full location path
  (e.g. *Drill → Tool Bin · Garage › Shelf*). Also powers HA voice/MCP.
- **Scan to find** — the camera scanner (QR + 1D barcodes) is **inventory-only,
  no outbound calls**: a known code opens the item, or shows a bin/location's
  contents; an unknown code lets you create or link it on the spot.
- **Photos on bins too** — attach photos/files to bins the same way as items.
- File **attachments** & photos (primary photo support)
- **Maintenance** logs per item with cost totals
- **CSV import/export** compatible with homebox's `HB.*` columns
- Auto asset IDs (`000-001`), group statistics & reporting
- Multi-tenant **groups** with invitations
- **Optional auth**: JWT login, or disable it entirely to run behind Home
  Assistant ingress (which already authenticates the user)
- Maintenance actions (ensure asset IDs / import refs, zero time fields, set
  primary photos)

### Web UI

The Vue 3 SPA is a full homebox-style interface:

- **App shell** with sidebar navigation, a global search bar, a **＋ Create**
  quick-add (item/bin/location/label), a **camera QR scanner** button, and a
  **light/dark theme** toggle (persisted).
- **Dashboard** with stat tiles, *recently added* item cards, and a locations
  overview.
- **Items**: card **grid ⇄ table** toggle, search, filter by location/label,
  sort (name / newest / updated / price), archived toggle, pagination.
- **Item detail** with tabs (Details · Attachments · Maintenance · QR),
  breadcrumb location path, hero photo, inline edit, attachment gallery, and a
  maintenance log form.
- **Location & bin detail** pages with tabbed items/bins/sub-locations and QR.
- **Maintenance** page aggregating scheduled/overdue/completed tasks group-wide.
- **Scanner** page using the browser `BarcodeDetector` API to scan a QR with the
  camera and jump straight to the item/bin/location (with a manual-entry
  fallback).
- Toasts, loading skeletons, and empty states throughout.

### Bins & QR codes

- A **bin** belongs to a location and contains items. Adding an item to a bin
  inherits the bin's location. Deleting a bin keeps its items (just detaches
  them). See the **Bins** tab.
- **QR codes** are managed from the QR panel on any item, bin, or location
  detail view. Each code has a short token and encodes a scan URL
  (`<app>/#/t/<token>`). Scanning opens the app, resolves the token, and
  navigates to the record. Scan URLs are **Home Assistant ingress aware** —
  they honor the `X-Ingress-Path` / `X-Forwarded-*` headers so printed codes
  keep working when the app is reached through ingress.

## Project layout

```
homehoard/
├── backend/            # Flask API + SQLAlchemy models
│   ├── app/
│   │   ├── api/        # route blueprints (items, bins, qr, checkout, search, ha, …)
│   │   ├── models/     # SQLAlchemy models
│   │   ├── schemas/    # JSON serializers (homebox-compatible camelCase)
│   │   ├── services/   # CSV import/export
│   │   ├── auth.py     # optional JWT auth layer
│   │   └── __init__.py # app factory (+ SPA serving, additive migrations)
│   ├── mcp_server.py   # MCP server exposed to Home Assistant (SSE)
│   ├── ha_discovery.py # Supervisor discovery registration
│   ├── seed.py         # demo data
│   ├── run.py          # dev entrypoint
│   └── tests/          # pytest suite
├── frontend/           # Vue 3 + Vite SPA
├── custom_components/  # HACS integration (custom_components/homehoard)
├── homehoard/          # HA add-on (config.yaml, DOCS.md, CHANGELOG.md)
├── repository.yaml     # HA add-on repository manifest (root, for Supervisor)
├── hacs.json           # HACS repository manifest
├── docker-entrypoint.sh# starts the app + MCP server in one container
├── Dockerfile          # standalone / add-on multi-arch image
└── docker-compose.yml
```

## Quick start (development)

Clone the repository:

```bash
git clone https://github.com/Amantux/homehoard.git
cd homehoard
```

Backend:

```bash
cd backend
pip install -r requirements.txt
python seed.py          # optional demo data
python run.py           # serves http://localhost:7745
```

Frontend (hot-reload dev server, proxies /api to :7745):

```bash
cd frontend
npm install
npm run dev             # http://localhost:5173
```

## Production / Docker

```bash
docker compose up --build
# → http://localhost:7745  (frontend + API from one container)
```

The image builds the Vue app and serves it from Flask, so a single container
runs the whole stack.



## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `HBOX_DATA_DIR` | `./data` | SQLite DB + attachments location |
| `HBOX_DATABASE_URL` | _(sqlite in DATA_DIR)_ | Override the SQLAlchemy URL |
| `HBOX_SECRET_KEY` | `change-me-in-production` | JWT signing key (use ≥ 32 chars) |
| `HBOX_DISABLE_AUTH` | `false` | Skip auth; bind all requests to a default local user/group |
| `HBOX_ALLOW_REGISTRATION` | `true` | Allow public self-registration |
| `HBOX_JWT_HOURS` | `168` | Token lifetime |
| `HBOX_MAX_UPLOAD_MB` | `50` | Max attachment upload size |
| `HBOX_PORT` | `7745` | App (API + UI) port |
| `HBOX_FRONTEND_DIST` | `../frontend/dist` | Built SPA directory |
| `HBOX_MCP_ENABLED` | `true` | Run the MCP server (in-container) |
| `HBOX_MCP_PORT` | `7766` | MCP SSE port |
| `HBOX_MCP_API` | `http://127.0.0.1:7745/api/v1` | API base the MCP server calls |
| `HBOX_MCP_API_TOKEN` | _(none)_ | Bearer token for the MCP server's API calls (only if app auth is on) |

Home Assistant add-on options: `disable_auth`, `allow_registration`, `enable_mcp`.

## API

JSON REST API under `/api/v1`, mirroring homebox's routes — e.g.
`/items`, `/items/{id}` (GET/PUT/PATCH/DELETE), `/items/import`,
`/items/export`, `/locations`, `/locations/tree`, `/labels`, `/groups/statistics`,
`/users/login`, `/users/self`, `/notifiers`, `/actions/*`, `/qrcode`, `/status`.

Bin & QR extensions:

| Method | Path | Description |
|---|---|---|
| GET/POST | `/bins` | List / create bins (`?location=<id>` filter) |
| GET/PUT/DELETE | `/bins/{id}` | Bin detail / update / delete (items kept) |
| PUT/DELETE | `/bins/{id}/items/{itemId}` | Add / remove an item to/from a bin |
| GET/POST | `/qr-tags` | List (`?kind=&targetId=`) / create a QR tag |
| GET/DELETE | `/qr-tags/{id}` | Get / delete a QR tag |
| GET | `/qr-tags/{id}/image` | PNG of the QR code |
| GET | `/qr-tags/resolve/{token}` | Resolve a scanned token to its target |

`POST /qr-tags` body: `{ "kind": "item"｜"bin"｜"location", "targetId": "<id>", "description": "optional" }`.

Search, scan, check in/out & Home Assistant:

| Method | Path | Description |
|---|---|---|
| GET | `/search?q=` | Find items, bins, and locations with a location path (`?types=item,bin,location`) |
| GET | `/barcode/{code}` | Inventory-only lookup — registered code → record (+ bin/location contents), else `not_found` |
| POST | `/items/{id}/checkout` | Check an item out (`{ person?, due?, notes? }`) |
| POST | `/items/{id}/checkin` | Check an item back in |
| GET | `/items/{id}/checkout` | Current status + check in/out history |
| GET | `/checkouts` | Everything currently checked out (with `overdue` flags) |
| GET | `/bins/{id}/attachments` … | Bin photos/attachments (mirrors item attachments) |
| GET | `/ha/summary` | Totals + attention counts (warranties expiring, maintenance overdue, checked out) |
| GET | `/ha/calendar?start=&end=` | Warranty-expiry + scheduled-maintenance events |

An **MCP server** (SSE on `:7766`) exposes these as tools for Home Assistant —
see [MCP server](#mcp-server-for-assist--llms) above.

## Tests & CI

```bash
cd backend
pip install -r requirements.txt pytest
pytest
```

GitHub Actions (`.github/workflows/ci.yml`) on every push to `main`: runs the
backend test suite + frontend build, **auto-bumps the patch version** (keeping
`homehoard/config.yaml` and the integration manifest in lockstep), then builds
the image **natively per arch** — amd64 on `ubuntu-latest`, **arm64 (Raspberry
Pi 5) on `ubuntu-24.04-arm`** — and merges them into a single multi-arch
manifest published to GHCR (`ghcr.io/amantux/homehoard:<version>` and `:latest`).

### Running on a Raspberry Pi 5

```bash
docker run -d --name homehoard -p 7745:7745 \
  -e HBOX_DISABLE_AUTH=false \
  -e HBOX_SECRET_KEY="$(openssl rand -hex 32)" \
  -v homehoard-data:/data \
  ghcr.io/amantux/homehoard:latest
```

## License

HomeHoard is a personal rewrite of homebox and, like homebox, is distributed
under the **GNU Affero General Public License v3.0** (see [`LICENSE`](LICENSE)).
