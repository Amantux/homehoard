# HomeHoard Report & Digest Row Inventory

Point-in-time inventory of **every report / digest row shape** the backend emits,
and of the fields each carries. Written from **direct reads of the source
emitters** — never inferred from tests or callers — so the field lists here match
the code exactly.

- **Scope:** report / digest payloads under `backend/` (plus the MCP + AI-agent
  surfaces that return the same shapes).
- **Audience:** the `ReportRow` consolidation work (parent task `t_d9d4e253`).
  This document is the inventory; the `ReportRow` shared-subset definition and the
  owner-review gate that follows are tracked separately.

## 1. Scope & method

Reports / digests inventoried (one table each in §3):

| # | Report / digest | Source (emitter) |
|---|---|---|
| 1 | `GET /api/v1/reports/inventory` | `backend/app/api/reports.py` — `inventory_report`, `_items`, `_row`, `_value`, `_warranty_status`, `_by` |
| 2 | `GET /api/v1/reports/inventory.csv` | `backend/app/api/reports.py` — `inventory_report_csv` |
| 3 | `alert_digest` | `backend/app/services/alerts.py` — `alert_digest`, `active_warranty_items`, `open_maintenance` |
| 4 | `restock_suggestions` / `restock_state` | `backend/app/services/restock.py` — `restock_state`, `restock_suggestions`, `in_several_places` |
| 5 | `GET /api/v1/ha/summary` | `backend/app/api/ha.py` — `summary` |
| 6 | `GET /api/v1/ha/calendar` | `backend/app/api/ha.py` — `calendar` |
| 7 | `GET /api/v1/checkouts` | `backend/app/api/checkout.py` — `all_checked_out` |
| 8 | `GET /api/v1/maintenance`, `GET /api/v1/items/{id}/maintenance` | `backend/app/api/maintenance.py` — `all_maintenance`, `list_entries` |
| 9 | CSV exports / item-row exports | `backend/app/services/csv_io.py` — `export_items`; `backend/app/api/misc.py` — `export`, `bill_of_materials`, `get_by_asset` |
| 10 | Group statistics | `backend/app/api/groups.py` — `statistics`, `purchase_price_stats`, `label_stats`, `location_stats` |

Consuming / re-shaping emitters that were read too, because they emit or project
report-shaped rows:

- `backend/app/api/items.py` — `restock` (`GET /restock`), `restock_restocked`
  (returns a restock row + purchase outcome).
- `backend/mcp_server.py` — MCP tools `inventory_value`, `inventory_statistics`,
  `warranties_expiring`, `maintenance_due`, `list_checkouts`, `whats_running_low`,
  `get_item`, `get_bin_contents`, `get_location_contents`, `list_hidden`, …
- `backend/app/services/ai/agent.py` — agent tools `list_restock`, `list_checkouts`,
  `get_item`, … returning the same row shapes.

## 2. Cross-report conventions (shared by all of them)

- **JSON keys** are camelCase and come from `backend/app/schemas/serializers.py`
  (`num`, `money.out`, `iso`/`iso_utc`) — homebox-compatible. A `Decimal` reaches
  the wire only through `money.out` (float) / `num` (int-or-float).
- **Money:** line value = `money.line_total(purchase_price, quantity)` (exact 2dp
  `Decimal` product, quantity kept at full precision) → `money.out` → float. Reports
  that sum use `money.total((price, qty) pairs)` and then round to 2dp.
- **Quantities:** `num(...)` — int when integral, float otherwise (never a string).
- **Dates:** stored naive-UTC (calendar dates at UTC midnight); emitted as ISO with
  `+00:00` (`iso`) or bare `YYYY-MM-DD` via `.date().isoformat()` (`iso_utc` /
  `to_local`). Comparisons that are *not* calendar-day based use aware-UTC
  comparison via `as_utc(...)` against `utcnow()`.
- **Attention comparisons use the LOCAL calendar day** (`to_local(now).date()`),
  never the stored value shifted and never a UTC comparison — see §3.3.
- **Vault:** every user-facing read goes through `vault.visible` /
  `vault.never_hidden` / `vault.readable` (`backend/app/services/vault.py`). Digest /
  HA surfaces that outlive the session use `never_hidden` or pass
  `include_hidden=False` explicitly.

## 3. Per-report inventories

### 3.1 `GET /api/v1/reports/inventory` — inventory valuation report (JSON)

Source: `backend/app/api/reports.py`.

Top-level keys: `generatedAt`, `currency`, `summary`, `byLocation`, `byLabel`, `items`.

`summary` keys: `totalItems`, `totalValue`, `insuredValue`, `uninsuredValue`,
`insuredCount`, `warranty` (`{lifetime, active, expiring, expired, none}` counts).

`byLocation` / `byLabel`: arrays of `{id, name, count, value}`, sorted by `value`
descending.

`items`: one row per item, sorted by `lineValue` desc.

Item row fields (emitted by `_row`):

| Field | Key | Type | Notes | Class |
|---|---|---|---|---|
| id | `id` | int | Item PK | Shared* |
| name | `name` | string | display name | Shared* |
| location | `location` | string | location name, `""` when unassigned | Report-specific |
| labels | `labels` | list[string] | label names | Report-specific |
| serialNumber | `serialNumber` | string | serial number, `""` when none | Report-specific |
| purchaseFrom | `purchaseFrom` | string | purchase-from, `""` when none | Report-specific |
| purchaseDate | `purchaseDate` | string\|null | ISO date | Report-specific |
| purchasePrice | `purchasePrice` | number | `money.out(...) or 0` | Report-specific |
| quantity | `quantity` | number | `num(...) or 1` | Report-specific |
| lineValue | `lineValue` | number | `money.out(money.line_total(purchase_price, quantity))` | Report-specific |
| insured | `insured` | bool | | Report-specific |
| warrantyStatus | `warrantyStatus` | string | `lifetime`/`active`/`expiring`/`expired`/`none` | Report-specific |
| imageId | `imageId` | string\|null | primary attachment `document_id` | Report-specific |

Aggregates & quirks:

- `totalValue = round(sum(r["lineValue"] for r in rows), 2)`; `insuredValue` =
  `round(sum(r["lineValue"] for r in rows if r["insured"]), 2)`; `uninsuredValue =
  round(totalValue - insuredValue, 2)`; `insuredCount = count(rows insured)`.
- `warranty` buckets: `lifetime` if `lifetime_warranty`; else `none` if no
  `warranty_expires`; else `expired` if `as_utc(warranty_expires) < now`; else
  `expiring` if `< now + 60 days` (`_EXPIRING_SOON_DAYS`); else `active`.
- Value is the **documented** value (purchase price × quantity); no depreciation is
  invented.
- `byLocation` aggregates only items that have a location; `byLabel` aggregates per
  label (an item with N labels contributes to each); unassigned items appear in
  `items` but in neither breakdown.

### 3.2 `GET /api/v1/reports/inventory.csv` — inventory valuation report (CSV)

Source: `backend/app/api/reports.py` — `inventory_report_csv`.

Header row: `Name, Location, Labels, Serial, Purchased from, Purchase date, Purchase price, Quantity, Line value, Insured, Warranty`

Data rows (per item, sorted by `lineValue` desc): `_csv_safe(...)` on name, location,
`"; ".join(labels)`, serialNumber, purchaseFrom; `purchaseDate or ""`;
`purchasePrice`, `quantity`, `lineValue`; `"yes" if r["insured"] else "no"`;
`r["warrantyStatus"]`.

- CSV-only differences from the JSON report: no `id`, no `imageId`; `insured` is the
  literal `"yes"` / `"no"`. Labels are `"; "`-joined inside one cell.
- Free-text cells get spreadsheet formula-injection neutralization
  (`_csv_safe`, CWE-1236); numeric/enum cells are written raw.
- Responds `text/csv` with `Content-Disposition: attachment; filename="homehoard-inventory-report.csv"`.

### 3.3 `alert_digest` — household alert digest

Source: `backend/app/services/alerts.py` — `alert_digest`, `active_warranty_items`,
`open_maintenance`.

Payload keys: `counts`, `overdueCheckouts`, `warrantyExpiringSoon`,
`maintenanceOverdue`, `isEmpty`, `text`.

`counts` keys: `restock`, `overdueCheckouts`, `warrantyExpiringSoon`,
`maintenanceOverdue` (counts of each).

Digest row shapes:

- `overdueCheckouts[]`: `{id, name, to}` — `to` = `checked_out_to` (may be `""`).
- `warrantyExpiringSoon[]`: `{id, name, expires}` — `expires` = `warranty_expires.date().isoformat()`.
- `maintenanceOverdue[]`: `{id, name, itemId, scheduled}` — `scheduled` = `scheduled_date.date().isoformat()`.

Quirks:

- `isEmpty` is `not any(counts.values())` — true when nothing needs attention.
- Plain-text `text`: one line per non-empty section, `\n`-joined, fallback
  `"No HomeHoard alerts."`. Lines: `Overdue for return (N): …` + `_link("/checkouts")`;
  `Running low (N): … (buy X)` + `_link("/restock")`; `Warranty expiring within 30 days
  (N): …` (no link); `Maintenance overdue (N): …` + `_link("/maintenance")`.
- `_link(path)` prefixes ` {base}/#{path}` only when `PUBLIC_URL` is configured, else `""`.
- Sections truncate name lists to the first 10 entries; `counts` carry the FULL list
  lengths.
- Attention uses the **local calendar day** (`to_local(now).date()`); warranty window
  is **30 days** here (vs. 60 in the inventory report).
- Restock input uses `restock_suggestions(group_id, include_hidden=False)` — never the
  default — because a notification outlives the session/lock.

### 3.4 Restock suggestions — `restock_suggestions` / `restock_state`

Source: `backend/app/services/restock.py`.

`restock_state(item) -> {id, name, onHand, threshold, target, suggestedQuantity, isLow} | None`
(`None` when the item has no `min_quantity`). `isLow =
on_hand <= threshold and not archived and sold_date is None`; `goal =
target if target > threshold else threshold + 1`; `suggestedQuantity =
round(max(goal - on_hand, 1), 4)`.

`restock_suggestions(gid, *, include_hidden=None) -> [{id, name, onHand, threshold,
target, suggestedQuantity}]` — `isLow` stripped before returning; sorted by
`(onHand, name.lower())`.

Surfaces that emit/project the same rows:

- `GET /api/v1/restock` → `{items, total}`.
- `GET /api/v1/ha/summary` → `restock: {count, items: [{id, name, onHand,
  suggestedQuantity, oneTap}]}` (first 20 shown; `oneTap` false when the item is in
  several placements).
- `POST /api/v1/restock/{item_id}/restocked` → returns `{...restock_state,
  bought, previousOnHand}` after a purchase.
- MCP `whats_running_low` and agent `list_restock` → the suggestion list.

### 3.5 `GET /api/v1/ha/summary` — Home Assistant attention summary

Source: `backend/app/api/ha.py` — `summary`.

Top-level keys: `health`, `restock`, `group`, `recentItems`, `checkedOutItems`,
`locations`, `totals`, `warrantiesExpiring`, `maintenance`.

- `restock: {count, items[]}` — `count` = all low; `items[]` = first 20 with
  `{id, name, onHand, suggestedQuantity, oneTap}`.
- `recentItems[]: {id, name, where, checkedOut}` — `where` from `item_where`
  ("Unassigned" fallback).
- `checkedOutItems[]: {id, name, to, overdue}`.
- `locations[]: {id, name, itemCount, binCount}` (first 12).
- `totals: {items, bins, locations, labels, value, insuredValue, withWarranty,
  checkedOut}` — `value`/`insuredValue` via `money.out(money.total(...))`;
  `withWarranty` counts items with `lifetime_warranty` **or** a `warranty_expires`
  (not "currently active").
- `warrantiesExpiring: {days30, days90, items[]}` — `items[]` is built from the
  **90-day** list (see quirk).
- `maintenance: {overdue, upcoming30, entries[]}` — `entries[]` carry
  `{id, name, itemId, itemName, scheduled, overdue}`.

Quirks: warranty sub-lists use the local calendar day with 30/90-day windows;
`overdue` flags use the local calendar day; aggregates are computed in SQL where
possible but money sums in Python (`money.total`).

### 3.6 `GET /api/v1/ha/calendar` — HA calendar events

Source: `backend/app/api/ha.py` — `calendar`.

Returns a bare JSON array of events:

- warranty: `{uid: "warranty-{itemId}", summary: "Warranty expires: {name}",
  start: "{expiryDate}", end: "{expiryDate+1}", category: "warranty",
  itemId}`.
- maintenance: `{uid: "maintenance-{entryId}", summary: "Maintenance: {name}"
  (+ " ({item})" if item), start: "{scheduledDate}", end: "{scheduledDate+1}",
  category: "maintenance", itemId}`.

Events sorted by `start`; ranges filtered by parsed `start`/`end`.

### 3.7 `GET /api/v1/checkouts` — currently checked out

Source: `backend/app/api/checkout.py` — `all_checked_out`.

Returns `{items: [...], total: n}`. Each item row = `item_summary(i)` plus
`checkedOutTo`, `checkedOutAt`, `checkoutDue`, `overdue`.

`item_summary` keys: `id, name, description, quantity, placementCount, insured,
archived, assetId, purchasePrice, imageId, location, bin, labels, checkedOut,
checkedOutTo, createdAt, updatedAt`.

Overdue comparison: `as_utc(checkout_due) < utcnow()` (instant-based), whereas the
digest / HA summary use the **local calendar day** — a documented inconsistency.

### 3.8 Maintenance entries

Source: `backend/app/api/maintenance.py` — `all_maintenance`, `list_entries`.

`GET /api/v1/maintenance` → `{entries: [...], costTotal}`. Rows = `maintenance_out`
(`{id, name, description, cost, scheduledDate, completedDate, recurMonths, itemId,
videos[]}`) plus `itemName`, `status` (`scheduled`/`completed`), `overdue`.

`GET /api/v1/items/{id}/maintenance` → `{entries: [...], costTotal, costAverage}`.

Quirks: group aggregate sums `cost` over **completed** entries only;
`overdue` = not completed and `as_utc(scheduled_date) < now` (instant-based).

### 3.9 CSV exports / item-row exports

Source: `backend/app/services/csv_io.py` — `export_items`; `backend/app/api/misc.py` —
`export` (`GET /api/v1/items/export`), `bill_of_materials` (`GET /api/v1/reporting/bill-of-materials`), `get_by_asset` (`GET /api/v1/assets/{asset_id}`).

- Export headers (`HEADERS` + `HB.field.<name>`): `HB.import_ref, HB.location,
  HB.labels, HB.quantity, HB.name, HB.description, HB.insured, HB.serial_number,
  HB.model_number, HB.manufacturer, HB.barcode, HB.notes, HB.purchase_from,
  HB.purchase_price, HB.purchase_time, HB.lifetime_warranty, HB.warranty_expires,
  HB.warranty_details, HB.sold_to, HB.sold_price, HB.sold_time, HB.sold_notes` plus
  one `HB.field.<custom field>` column per custom field present.
- Export row cells: import ref, location name, `";"`.join(label names), `num(quantity)`,
  name, description, insured, serial, model, manufacturer, barcode, notes,
  purchase_from, purchase_price, `purchase_date.date().isoformat()`,
  `lifetime_warranty`, `warranty_expires.date().isoformat()`, warranty_details,
  sold_to, sold_price, `sold_date.date().isoformat()`, sold_notes, then custom fields.
- Vault: a **locked** export omits hidden rows; unlocked = complete.
- `/reporting/bill-of-materials` returns the same CSV as `bom.csv`; `/assets/{id}`
  returns `{items: [item_summary…], total}`.

### 3.10 Group statistics

Source: `backend/app/api/groups.py`.

- `GET /api/v1/groups/statistics` → `{totalItems, totalLabels, totalLocations,
  totalUsers, totalWithWarranty, totalItemPrice}`.
- `GET /api/v1/groups/statistics/purchase-price` → `{total, entries: [{date, value}]}`.
- `GET /api/v1/groups/statistics/labels` / `locations` → arrays of `{id, name, total}`.

## 4. MCP & AI-agent emitters (report-shaped rows)

| Tool / agent tool | Backing | Returns |
|---|---|---|
| MCP `inventory_value` | `GET /reports/inventory` | `{currency, totalValue, insuredValue, uninsuredValue, itemCount, byLocation, byLabel, warranty}` |
| MCP `inventory_statistics` | `GET /ha/summary` | `{...totals, warrantiesExpiring30d, maintenanceOverdue}` |
| MCP `warranties_expiring` | `GET /ha/summary` | `warrantiesExpiring.items[]` |
| MCP `maintenance_due` | `GET /ha/summary` | `maintenance.entries[]` |
| MCP `list_checkouts` | `GET /checkouts` | `[{name, to, overdue}]` |
| MCP `whats_running_low` | `GET /restock` | restock rows |
| MCP `get_item` / agent `get_item` / `where_is` | item serializers / `_item_brief` | `{id, name, description, quantity, manufacturer, modelNumber, labels, placements[]}` |
| MCP `get_bin_contents` / `get_location_contents` | `/bins` `/locations` | contents rows |
| MCP `list_hidden` / agent `list_hidden` | `/items?onlyHidden=true` | `[{id, name}]` |

## 5. Emitter coverage checklist

Every function that emits a report/digest-shaped payload found in `backend/` is
covered by the tables in §3:

- [x] `backend/app/api/reports.py` — `inventory_report`, `inventory_report_csv` (§3.1–3.2)
- [x] `backend/app/services/alerts.py` — `alert_digest` + helpers (§3.3)
- [x] `backend/app/services/restock.py` — `restock_state`, `restock_suggestions` (§3.4)
- [x] `backend/app/api/ha.py` — `summary`, `calendar` (§3.5–3.6)
- [x] `backend/app/api/checkout.py` — `all_checked_out` (§3.7)
- [x] `backend/app/api/maintenance.py` — `all_maintenance`, `list_entries` (§3.8)
- [x] `backend/app/services/csv_io.py` + `backend/app/api/misc.py` — exports (§3.9)
- [x] `backend/app/api/groups.py` — statistics (§3.10)
- [x] `backend/mcp_server.py` + `backend/app/services/ai/agent.py` — MCP/agent rows (§4)

## 6. Shared vs report-specific fields

A field is **shared** when it is present in every report/digest row shape; otherwise it
is **report-specific**. Derived from the inventories above:

| Field | Present in | Class |
|---|---|---|
| `id` | inventory rows, digest rows, restock rows, checkouts, maintenance, stats, … | Shared* |
| `name` | inventory rows, digest rows, restock rows, checkouts, maintenance, stats, … | Shared* |
| `insured` / `insuredValue` / `insuredCount` | inventory, HA summary, item_summary | Report-specific |
| `lineValue` / `totalValue` / `value` / `totalItemPrice` / `total` / `costTotal` | inventory, HA summary, restock, stats, BOM | Report-specific |
| `warrantyStatus` / `warranty` / `warrantiesExpiring` / `expires` / `lifetime_warranty` | inventory, digest, HA summary/calendar, stats | Report-specific |
| `purchasePrice` / `purchaseFrom` / `purchaseDate` / `serialNumber` / `imageId` / `location` / `labels` | inventory, item_summary, exports, `_item_brief` | Report-specific |
| `quantity` / `onHand` / `threshold` / `target` / `suggestedQuantity` / `minQuantity` / `targetQuantity` | inventory, restock, HA summary, checkouts, `_item_brief`, exports | Report-specific |
| `checkedOut` / `checkedOutTo` / `checkedOutAt` / `checkoutDue` / `overdue` / `to` | checkouts, HA summary, MCP `list_checkouts` | Report-specific |
| `scheduledDate` / `scheduled` / `completedDate` / `status` / `cost` / `recurMonths` / `itemId` / `itemName` | maintenance, calendar, digest, stats | Report-specific |
| `isEmpty` / `text` / `counts` / `_link` / `generatedAt` / `currency` / `health` / `group` / `where` / `placements` / `videos` | envelope of a single report | Report-specific |

The formal `ReportRow` shared-subset definition — including the per-report
extras-as-extensions rule — lives in §7. The candidate shared identity fields
above (`id`, `name`) are its entirety, and that definition must not be adopted
before owner review.

## 7. The `ReportRow` shared subset

### 7.1 Definition

`ReportRow` is **the minimal field set present in every report / digest row**
emitted by the backend — the intersection of every report / digest row shape
inventoried in §3 and surfaced in §4:

| Field | Type | Shared? | Where it appears |
|---|---|---|---|
| `id` | int | **Yes** | every report / digest row (§3.1–3.10, §4) |
| `name` | string | **Yes** | every report / digest row (§3.1–3.10, §4) |

That is the entire shared subset, and it is deliberately just these two fields:

```json
{
  "id": 0,
  "name": ""
}
```

No third field survives the intersection: every other field the reports carry
(`location`, `labels`, `serialNumber`, `purchasePrice`, `quantity`, `lineValue`,
`insured`, `warrantyStatus`, `imageId`, `onHand`, `threshold`,
`suggestedQuantity`, `checkedOutTo`, `expires`, `scheduled`, `cost`, …) varies
per report, so it is report-specific rather than shared.

### 7.2 Per-report extras are extension fields — allowed, never padding

- A report / digest **may** include fields it has data for beyond the `ReportRow`
  subset; those are **extension fields**, and they are **allowed**.
- Extension fields are allowed **never as padding**: a field must map to real data
  the emitter already holds, and must not be invented merely to satisfy the subset.
- **No report may be forced to pad or drop fields to satisfy the `ReportRow`
  contract.** The contract fixes only the shared minimum; it never asks a report
  to fabricate or remove a field.

### 7.3 Owner-review gate

> **Owner-review gate — BLOCKED.** The `ReportRow` contract in §7 is **blocked**
> until the owner reviews the inventory in §3. The contract is **not adopted**
> before that review; it is not approved, and no consolidation work may adopt or
> implement it until the owner signs off.

The `ReportRow` shared-subset definition above is **derived from the inventory
in §3** and states that the contract **must not be adopted before owner review**;
it is a proposal for the consolidation work of parent task `t_d9d4e253`, not an
approved contract. No report code has been changed to enforce or consume it.

### 7.4 Shared-subset table — field → where it appears

| Shared field | Type | Appears in every report / digest |
|---|---|---|
| `id` | int | inventory `items` / `byLocation` / `byLabel`; digest rows; restock rows; HA summary lists; checkouts; maintenance; group statistics; MCP + agent rows |
| `name` | string | inventory `items`; digest rows; restock rows; HA summary lists; checkouts; maintenance; group statistics; MCP + agent rows |

Task verification:

- [x] The shared subset was derived by intersecting the field sets of every
      inventoried row shape (see §3 / §4) — not assumed.
- [x] Every report's extras are listed as allowed extensions (§6).
- [x] The doc states the contract must not be adopted before owner review (§7.3).

---
