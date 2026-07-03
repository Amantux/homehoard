# HomeHoard 📦

**HomeHoard is my own personal rewrite of [homebox](https://github.com/hay-kot/homebox).**

I love what homebox does, but I wanted three things it didn't give me, so I
rebuilt it from the ground up in Python:

1. **Home Assistant, done properly.** HomeHoard runs as a first-class HA **add-on**
   (one-click install, Ingress, no separate login) and ships a companion
   **HACS integration** that surfaces your inventory — item counts, total value,
   locations — as Home Assistant sensors.
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
- File **attachments** & photos (primary photo support)
- **Maintenance** logs per item with cost totals
- Full-text-ish **search** + filter by location/bin/label, pagination
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
│   │   ├── api/        # route blueprints (users, items, locations, …)
│   │   ├── models/     # SQLAlchemy models
│   │   ├── schemas/    # JSON serializers (homebox-compatible camelCase)
│   │   ├── services/   # CSV import/export
│   │   ├── auth.py     # optional JWT auth layer
│   │   └── __init__.py # app factory (+ SPA serving)
│   ├── seed.py         # demo data
│   ├── run.py          # dev entrypoint
│   └── tests/          # pytest suite
├── frontend/           # Vue 3 + Vite SPA
├── custom_components/  # HACS integration (custom_components/homehoard)
├── homehoard/            # HA add-on (config.yaml, DOCS.md)
├── repository.yaml     # HA add-on repository manifest (root, for Supervisor)
├── hacs.json           # HACS repository manifest
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
| `HBOX_PORT` | `7745` | Dev server port |
| `HBOX_FRONTEND_DIST` | `../frontend/dist` | Built SPA directory |

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

## Tests & CI

```bash
cd backend
pip install -r requirements.txt pytest
pytest
```

GitHub Actions (`.github/workflows/ci.yml`) runs the backend test suite and the
frontend build on every push, then builds a **linux/arm64 Docker image for the
Raspberry Pi 5** and publishes it to GHCR (`ghcr.io/amantux/homehoard`).

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
