# Open Food Facts (OFF) API Dependency

HomeHoard relies on the public Open Food Facts API to provide automated product identification for scanned barcodes, specifically for grocery and food items.

## What and Why
When a user scans a 1D barcode (UPC/EAN) that is not already in their inventory or a private product database, HomeHoard queries the Open Food Facts API. This allows the system to suggest a product name and brand, reducing manual entry during the "onboarding" or "add item" flow.

## Contract We Rely On

### Request Shape
- **Endpoint:** `GET https://world.openfoodfacts.org/api/v2/product/{barcode}.json`
- **Path Segment:** The barcode is URL-quoted (all characters escaped) to prevent path traversal or request reshaping.
- **Headers:** `User-Agent: HomeHoard/1.0`
- **Authentication:** None (Public API).
- **Timeout:** 6 seconds.

### Response Fields Consumed
The API returns a JSON object. HomeHoard consumes the following:
- `status`: Must be `1` for a successful match.
- `product.product_name`: Primary name used for the suggestion.
- `product.generic_name`: Fallback name if `product_name` is missing.
- `product.brands`: A comma-separated string; only the first segment is used as the brand name.

### What Counts as a Miss
A lookup is considered a miss (returning `None` to the caller) if:
1. The network request fails or times out.
2. The response status code is not 200 OK.
3. The JSON `status` field is not `1`.
4. Both `product_name` and `generic_name` are missing or empty.

## Position in the Lookup Chain
Barcode identification is a sequential, best-effort chain. If one source misses, the next is tried. The entire chain is gated by the `BARCODE_LOOKUP` configuration switch.

1. **Private Product DB:** `_from_product_db()` (requires `BARCODE_DB_URL`).
2. **Open Food Facts:** `_from_off()` (hardcoded host).
3. **AI Web Search:** `_from_web_search()` (requires configured AI provider).

## Call Sites

| Path:Line | Symbol | Role |
|---|---|---|
| `backend/app/services/barcode.py:54` | `_from_off` | Implementation of the OFF API request and parsing. |
| `backend/app/services/barcode.py:125` | `identify_barcode` | Orchestrates the lookup chain (DB $\rightarrow$ OFF $\rightarrow$ Web). |

## Consumers

| Path:Line | Symbol | Role |
|---|---|---|
| `backend/app/api/items.py:842` | `identify_item` | API endpoint `GET /api/v1/items/identify/<code >` providing suggestions to the UI. |
| `frontend/src/components/ScannerModal.vue:220` | `identifyProduct` | Frontend call to the identify endpoint during barcode scanning. |

## Data Crossing the Trust Boundary

### Outbound
- **Data:** Only the scanned barcode string is sent to the external host.
- **Privacy:** No household data, user IDs, or inventory details ever leave the system.
- **Security:** The host is hardcoded; only the quoted barcode is appended to the path, limiting the SSRF surface to the OFF domain.

### Inbound
- **Data:** Product names and brand strings are received.
- **Persistence:** No data from the OFF API is persisted to the database until the user explicitly saves the item via the create-item form.
- **Sanitization:** Names are stripped of leading/trailing whitespace.

## Failure Behaviour and Operator Knobs

### Operator Controls
- **Kill Switch:** Set `HBOX_BARCODE_LOOKUP=false` to disable all outbound barcode lookups.
- **Egress Requirements:** Firewall/Proxy must allow outbound HTTPS (port 443) to `world.openfoodfacts.org`.

### Reliability and Performance
- **Latency Budget:** Each hop has a 6-second timeout. Total worst-case latency for a full chain miss is $\sim 18$ seconds.
- **Cache:** No response caching is implemented; every identification request triggers a new network call.
- **Retry/Backoff:** No automatic retries or exponential backoff are used for the OFF hop.
- **Rate Limiting:** The `GET /api/v1/items/identify/<code >` endpoint is limited to **30 requests per minute** via `Flask-Limiter` to prevent abuse of the outbound API.
- **429 Handling:** No specific handling for HTTP 429 (Too Many Requests) from OFF; such responses are treated as generic failures and log an INFO message.

## Tests

| Test File | Focus | How to Run |
|---|---|---|
| `backend/tests/test_barcode.py` | Mocked chain logic and fall-through behaviour. | `pytest` |
| `backend/tests/test_barcode_ssrf.py` | Verification that codes are quoted and cannot reshape the URL. | `pytest` |
| `backend/tests/test_integration_barcode.py` | Live smoke test against the real OFF API. | `RUN_INTEGRATION=1 pytest ...` |

## Known Gaps
- **Hardcoded Host:** The OFF API host is hardcoded and cannot be overridden via configuration (e.g., for mirrors).
- **User-Agent:** The `User-Agent` is a generic string and does not include a contact URL or identifier for OFF administrators.
- **No Cache:** Redundant lookups for the same barcode are not cached.
- **No 429/Backoff:** The system does not respect or react to rate-limit signals from the upstream API.

## Change Procedure
Adding or removing a call site, changing the API URL, or modifying the consumed response fields requires updating this document. The guard test in `backend/tests/test_dependency_inventory.py` enforces that all code references to Open Food Facts are mirrored in this inventory.
