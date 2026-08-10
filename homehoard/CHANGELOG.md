# Changelog

## Unreleased

- **New: a vault for items you'd rather nobody saw.** Mark an item hidden and it
  disappears from every list, search, count, price total, export, HA sensor,
  notification and assistant answer until you unlock it with a passphrase you
  set. Ask the assistant to "unhide my items", give the phrase, and they stay
  visible until you say "lock" (or log out, or 12 hours pass). Unlocking applies
  to the session you did it in, so unlocking on a laptop doesn't reveal anything
  on a phone, and an API token never inherits it.
- **If you forget the vault passphrase, it cannot be recovered** — it is stored
  only as a hash. You can reset the vault, but doing so **permanently deletes
  everything in it**; the reset previews a count first and needs an explicit
  confirmation. It deletes rather than re-keying deliberately, so that an owner
  cannot simply re-key their way into reading it.
- **The vault is access control inside the app, not encryption.** Hidden items
  are still stored as ordinary rows, so anyone with your database file, a backup
  or an admin API token can read them regardless. And if you unlock by chatting
  with the assistant, the passphrase goes to your LLM provider and stays in the
  chat history — unlock from the UI if that matters to you.

- **HomeHoard now checks its settings before it starts.** If something is wrong
  — a typo in an option, a port already in use by the MCP server, an unusable
  database URL — it says so in the log, lists *every* problem at once, and stops
  instead of starting up and failing later in a way that looks like a bug.
- **Read this before updating if you edited options by hand.** A setting that
  isn't a valid yes/no (something like `maybe`) used to be quietly treated as
  "no". It is now an error, so an add-on that has been running on a typo will
  refuse to start until you correct it. The log names the option and what it
  accepts. Options set through the Configuration tab are unaffected.
- The startup log now shows which settings are non-default and where each came
  from (add-on option, environment, or built-in), which is the fastest way to
  answer "but I set that". Passwords, keys and database URLs are redacted —
  including credentials embedded in a provider URL.
- Fixed: with an incomplete options file, self-registration could be left
  enabled when it should have been off.

## 1.1.0 — Stable release

A stability milestone bringing this cycle's work together.

- **Faster capture.** Scan a barcode to create a bin, snap a photo when creating an
  item, and stock the same item in a bin more than once (quantities combine). Camera
  photos now save the right way up, and search no longer jumps you off the item
  you're on.
- **One database, one AI setup across your apps.** Auto-provision HomeHoard's database
  on the **Shared PostgreSQL** add-on (opt-in — `use_shared_postgres`), copy AI provider
  settings between HomeHoard / Edibl / myMeal (optionally including the key), and a
  Database-page helper for pointing all three at one Postgres.
- **MCP, reachable and safe.** Expose the MCP server outside Home Assistant behind
  per-client, revocable API keys (`mcp_expose_external` + a new mapped port). Every key
  now has an **access class — Read-Only or Read-Write** — and a scope (Full / REST /
  MCP), enforced on both the API and the MCP tools.
- **Report a bug from chat.** The assistant walks you through a short report and opens
  a prefilled GitHub issue; streaming replies are a Settings toggle.
- **Understand scanned barcodes (1D + 2D).** Items now carry a product barcode,
  and scanning distinguishes 1D product codes (UPC/EAN/Code128…) from 2D codes
  (QR/DataMatrix…). Scanning a code you've saved on an item jumps straight to it.
  With the new `barcode_lookup` option on, scanning an unknown product identifies
  it online (product DB → Open Food Facts → Ollama web-search) and prefills the
  new item's name — all still optional and off by default; scans resolve your own
  tags and items offline either way. New `barcode_lookup` / `barcode_db_key`
  add-on options. You can also type or paste a barcode straight onto an item from
  its detail page, and the barcode now round-trips through CSV import/export
  (new `HB.barcode` column).

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
