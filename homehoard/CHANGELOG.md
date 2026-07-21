# Changelog

## 1.0.10

- **The same item in multiple places.** An item can now be stocked across several
  bins/locations with a quantity in each (e.g. "20 AA batteries: 8 in the kitchen
  drawer, 12 in the garage bin"), rolling up to a total. The item page has a
  **Placements** section to add, edit, move, and remove placements; a bin or
  location now shows each item's quantity **there**; and item cards note "in N
  places". Assist/MCP can add a placement and read where things are stocked by
  voice. Existing items are migrated automatically (each becomes one placement),
  and single-placement items work exactly as before.

## 1.0.8

- **Multi-user behind Home Assistant.** Each HA user now gets their own HomeHoard
  identity (auto-provisioned from the ingress sign-in), all sharing one
  household — so items, bins, and locations are shared but identity is
  per-person. The **first** user is the **owner** and can change household config
  (API keys, household name/currency, invitations); everyone else is a **member**
  with full inventory use. Trust boundary enforced: the identity headers are
  honored only from the Home Assistant Supervisor proxy — a forged header from a
  directly published port is ignored. Standalone installs are unchanged.

## 1.0.0
- **First stable release.**
- **Nested locations / multi-site support** — sites (homes, storage lockers,
  rentals) with rooms, shelves, and bins nested inside, as a navigable tree.
- **Free-text create flow** — natural-language quick-add, create-on-the-fly
  bin/location pickers, and one-tap suggested placements.
- **Bulk item actions** (move / label / archive / delete).
- **API tokens + in-app Home Assistant page** so a standalone (auth-enabled)
  instance can connect the HA integration; the integration now sends its token
  on every call (sensors **and** calendar).
- **`suggest_placement` MCP tool** — "where should this go?" (13 MCP tools).
- MCP + an LLM Assist pipeline is now the recommended voice/chat path.

## 0.2.0
- **Rebrand: Shelfie is now HomeHoard.** New name, add-on slug (`homehoard`),
  image (`ghcr.io/amantux/homehoard`), and companion integration domain
  (`homehoard`). If you ran the old add-on/integration, reinstall under the new
  name. Fresh database — start hoarding!

## 0.1.1
- **Fix: add-on failed to install (`manifest unknown`, 404).** The add-on is now
  published to GHCR under a version tag that matches `config.yaml`, so Supervisor
  can pull `ghcr.io/amantux/homehoard:<version>`.
- CI now auto-bumps the patch version on every push and publishes a matching
  multi-arch image (amd64 + aarch64 / Raspberry Pi 5).

## 0.1.0
- Initial release of the **HomeHoard** Home Assistant add-on.
- Home inventory & organization — a personal rewrite of homebox.
- Ingress UI (no separate login when `disable_auth` is on), QR codes & barcodes,
  and moving-box **bins**.
- Registers Supervisor discovery so the companion HACS integration configures
  itself automatically.
