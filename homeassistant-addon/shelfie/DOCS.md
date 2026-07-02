# Shelfie

Home inventory & organization — a personal rewrite of
[homebox](https://github.com/hay-kot/homebox) with first-class Home Assistant
support, QR codes / barcodes, and moving-box "bins".

## Installation

1. Add this repository to the add-on store, or install directly if you found it
   via the Shelfie repository.
2. Install **Shelfie** and start it.
3. Open it from the sidebar (Ingress) — no separate login needed.

## Options

| Option | Default | Description |
|---|---|---|
| `disable_auth` | `true` | Skip in-app auth (Ingress already authenticates you). Set `false` for username/password login. |
| `allow_registration` | `false` | Allow creating new accounts (only relevant when auth is enabled). |

Data (SQLite database + attachments) is stored under `/share/shelfie`.

## Companion integration

Install the **Shelfie** HACS integration to expose your inventory as Home
Assistant sensors (total items, total value, locations, …). When this add-on is
running, Home Assistant will offer the integration automatically via discovery.
