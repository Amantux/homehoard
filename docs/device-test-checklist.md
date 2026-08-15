# Device-test checklist

Everything here shipped verified by tests and CI but **never rendered on a real
screen or touched by real hardware** — the two things automation in this repo
cannot do. Each item says what to try and what "broken" would look like.
Ordered so the highest-risk items are first; the whole pass is ~15 minutes.

## Phone (390px-class), via HA ingress

1. **Items grid with a long name** — find/create an item with a very long name
   (e.g. the full DeWalt kit name). Its card should clamp to two lines and stay
   the same size as its neighbours. *Broken: one stretched card, ragged grid.*
2. **Any table (Items table view, Checked out, Restock, Maintenance)** — the
   table should scroll sideways *inside its card*; the page itself must never
   pan horizontally. *Broken: the whole page shifts and the nav drifts off.*
3. **Bin → create item with photo** — 📷 Photo, shoot, name it, Create. The
   item should appear with its thumbnail. Then the create row again: does the
   staged-photo chip + Create button wrap acceptably at this width?
4. **Duplicates page** — create two "Test dupe" items, open ⧉ Duplicates,
   merge. Confirm the dialog text, then that the survivor holds both
   placements. (After the current fleet lands: check the Undo toast button.)
5. **Dashboard "Needs attention" strip** — with an overdue checkout it should
   read cleanly; with nothing due it should be entirely absent.
6. **Vault** — Items → 🔒 chip → wrong phrase (persistent error toast), right
   phrase, 🔓 lock again. On a *second* device: still locked.

## Desktop

7. **QR tab + hardware scanner (if you have one)** — open any item's QR tab:
   the code field should already have focus; a trigger pull should type + Enter
   + link in one motion. *Broken: focus elsewhere, scan goes nowhere.*
8. **Label sheet print preview** — Tools → QR label sheet → select a few →
   Print. In the preview: 3-across grid, ~63×38 mm cells, no clipped codes,
   sane page breaks. *This is the least-verified layout in the app.*
9. **`/` opens search; search "battery"** — should find "batteries" items.

## HA side

10. **Restock block** — `/api/v1/ha/summary` shows `restock`; after the fleet
    lands, the to-do entity should mirror it.
11. **Notification digest** — trigger `POST /notifiers/dispatch` (or wait for
    your automation): links present only if `public_url` is set, and no
    vault-hidden item ever named.

Anything that fails: note which numbered item and what you saw — each maps to
one specific commit.
