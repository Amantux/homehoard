# Changelog

## 1.1.55

- Maintenance release.

## 1.1.54

- **Restoring a Home Assistant backup never has to guess.** While HA archives
  the add-on, saves are briefly refused with a clear message (reads keep
  working), so the consistent database copy in the backup is always the one a
  restore uses.
- You can change your password from the user menu.

## 1.1.53

- **Home Assistant backups no longer restart the add-on.** While it runs, the
  backup also carries a consistent copy of the database, which a restore
  prefers; a backup of a stopped add-on still contains the database. A stale
  copy left by an interrupted backup is cleaned up automatically. (Postgres
  users: keep using pg_dump.)
- **Changing your password now signs out every other session**, and API keys
  can be given an optional expiry date — enforced for the web API and the MCP
  server alike.
- HomeHoard picks up your Home Assistant time zone at start-up (override with
  `HBOX_TZ`). Stored timestamps stay UTC and item dates are never shifted; but
  overdue maintenance, expiring warranties and overdue lends now roll over at
  midnight in your zone instead of UTC.
- Stopping the add-on during the first seconds of boot is honoured instead of
  being ignored until the kill timeout.
- The web app can be installed to a phone's home screen when opened directly
  (outside Home Assistant).

## 1.1.52

- **Your lists stay current.** A list refreshes right after you save, loads no
  longer overlap and overwrite each other, and background sync stops when you
  sign out.
- Background refreshes no longer clear a bulk selection or an edit you're in the
  middle of, the list stays on screen while you filter it, and the delete
  confirmation names the items it will delete.
- The barcode scanner turns the camera off if you close it before it finishes
  starting, offers Retry when it can't start, loads its reader in advance so it
  opens faster, and says plainly when linking a code is unavailable.
- The assistant panel announces new replies to screen readers and puts focus
  where you expect when it opens and closes.
- Reports: purchase dates display correctly, the currency symbol recovers if it
  failed to load at start-up, and picker fields no longer act after you've moved
  on from them.
- **When your session expires you get a banner, not a broken page.** Signing in
  again returns you to the page you were on.
- Typing the wrong vault passphrase no longer signs you out.
- MCP tool calls now act as the household that owns the API key, and a
  read-only key stays read-only there too.
- Home Assistant discovery waits until HomeHoard is ready, and rediscovery
  updates the existing entry instead of adding a duplicate.
- Behind the scenes: the secret scanner's test allowlist is anchored to exact
  values, CI tests the integration on Home Assistant 2024.11.0 and the latest
  release, and backend dependencies are pinned.
- **Upgrades are safer.** Before migrating an existing database HomeHoard saves
  a copy to `/data/backups/pre-upgrade-*.db` (the last two are kept) and refuses
  to upgrade if that copy can't be written. Stopping the add-on during start-up
  no longer kills it mid-migration. Home Assistant backups now stop HomeHoard
  for a few seconds so the backup holds a consistent copy of your database —
  expect a brief restart during nightly backups.
- Fixed: installing on PostgreSQL no longer fails during database setup with
  "default expression is of type integer". CI now boots a fresh install against
  a real PostgreSQL on every change.
- If you run the MCP server outside the add-on with your own API key as its
  token, keyed tool calls are now rejected; the server says so at start-up.
  Leave the token unset to use the integration token.
- **Keyboard and screen-reader users can now get around.** Item, bin and
  location cards are real links with a visible focus ring; every page has a
  heading and its own browser-tab title, focus moves to it when you change
  page, Back restores your scroll position; the account menu closes with Esc
  or a click outside; notifications are announced, pause while you hover
  them, and old errors clear when you change page; photos have descriptions;
  maintenance status reads "Overdue"/"Done"/"Scheduled" rather than relying
  on colour; the sign-in form works with password managers and Enter.
- Confirmation dialogs close when you navigate away instead of lingering over
  the next page. If the server fails or the network drops mid-chat you get a
  clear message, and one garbled line from the AI no longer cuts off the reply.
- Settings that fail to load now say so and can be retried, with Save disabled
  until they do, so a network hiccup can't overwrite your real AI or chat
  settings with defaults. Vault status failures are shown instead of hidden.
- The "move an existing item" and scan-to-link pickers search all your items
  instead of stopping silently at 500, and Duplicates says when it only
  checked part of a large inventory.
- Sign-up, profile and location forms reject malformed input with a clear
  message instead of a server error, and the built-in Home Assistant and
  local account addresses can no longer be claimed. The login response no
  longer includes the unused `attachmentToken` field.
- Faster page loads in open/ingress mode: the legacy-password safety check
  runs once per user instead of on every request, and a busy database no
  longer turns a valid API-key request into an error.
- Locations and the Home Assistant summary load faster for large households
  (counts come from the database instead of loading every item), hidden items
  no longer show up in the summary's per-location counts while the vault is
  locked, a corrupted location hierarchy can't crash the location tree, and
  the HA calendar accepts start/end times with any UTC offset.
- The assistant no longer passes internal error details (which could include
  connection strings) to the AI model or into chat history when a tool fails;
  you see "internal error, ref <id>" and the same id appears in the add-on
  log. Validation messages still come through so the assistant can correct
  itself.
- A notifier that fails to send now logs a warning with the error type and
  provider, never the URL or its token. Login and registration rate limits
  are covered by tests (the limit applies per server worker, so the effective
  limit is twice the configured value).
- The app's initial download is about 19% smaller: the scanner, search,
  create and bug-report dialogs load on demand.
- Behind the scenes: CI now boots the container on an older database to prove
  an upgrade takes a backup first and keeps your data, checks that stopping
  during start-up exits cleanly and that the voice/MCP server comes back after
  a crash; the container healthcheck follows `HBOX_PORT`; the Documentation
  tab gains "Backup and restore" and "Time zone" sections and the voice-sentence
  install steps, and corrects where data is stored (`/data`) and what
  `log_level` hides; chat sessions, background jobs, AI suggestions and
  notifiers all use the shared household check and the cross-household test
  now covers them, foreign ids in request bodies, and another member's
  notifiers.

## 1.1.51

- **Read this before updating: quantities are now exact decimals.** On first
  start after the update HomeHoard rebuilds its quantity tables and rounds every
  stored quantity to 3 decimal places, so a large inventory can take a little
  longer to come up once. Afterwards 0.1 + 0.2 really is 0.3, and a quantity
  with more than 3 decimals (or a yes/no value) is rejected with a clear error
  instead of being stored as-is.
- **Timestamps from the API now carry an explicit UTC offset** (`+00:00`).
  If you wrote an automation or script that parses HomeHoard dates, check it
  still does. Dates in the app no longer show a day early west of UTC.
- **The MCP (assistant/voice) server restarts itself if it crashes**, instead of
  staying down until you restart the add-on, and `/ready` reports whether it is
  up.
- New option `mcp_require_key`: turn it on to require an API key for every MCP
  request, even from inside Home Assistant. Off by default, so nothing changes
  unless you set it.
- **Security fixes.** Read-only API keys are now enforced on every route, not
  just most of them. Printing QR labels no longer runs script hidden in an item
  name. The barcode lookup URL is validated before it is used. Error messages
  no longer echo internal details such as AI provider responses.
- If login is disabled and HomeHoard is reached outside Home Assistant, the app
  and the log now warn you that anyone who can reach that port has full access.
- **Easier to use with a keyboard, touch screen or screen reader:** larger tap
  targets, labelled icon buttons, dialogs that keep focus and close with Esc,
  list rows you can tab to, and error messages that are announced.
- Detail pages show loading, error and not-found states instead of a blank
  screen, a mistyped address shows a proper not-found page, and buttons say what
  they are doing while they work ("Saving…").
- Faster: location and bin lists load in fewer queries, pages load on demand,
  and the bin item picker searches as you type.
- Home Assistant discovery retries in the background if Home Assistant isn't up
  yet when the add-on starts.
- The companion integration now needs **Home Assistant 2024.11.0 or newer**.
- You stay signed in across this update.

## 1.1.50

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
