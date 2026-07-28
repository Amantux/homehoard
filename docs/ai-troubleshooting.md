# AI features — troubleshooting guide (TSG)

Covers the shared AI stack across **HomeHoard**, **Edibl**, and **myMeal**: the
provider picker, the chat assistant, background enrichment, and "AI organize"
(auto-categorize + cluster) with its review queue.

## How to use this guide (for humans and LLMs)

Each issue is a fixed schema so it can be matched and acted on programmatically:

- **ID** — stable identifier (`T-##`).
- **Symptom** — what the user observes (error text, HTTP status, or behavior).
- **Apps** — which apps it applies to.
- **Cause** — the underlying reason.
- **Fix** — the concrete action.
- **Verify** — how to confirm it's resolved.

To match a report: read the **Symptom** lines top-to-bottom; the first match wins.
Where a setting differs per app, substitute the env prefix and UI location from the
**App reference** table at the end. All API paths are under `/api/v1`.

---

## 0. Quick triage (decision order)

1. Is a provider selected at all? → **T-01**.
2. Provider selected but calls fail with "not fully configured"? → **T-02**.
3. Using a local SLM and it can't connect? → **T-03**, **T-04**, **T-05**.
4. Enrichment / import-by-name finds nothing? → **T-10**.
5. A job stays `pending` forever? → **T-20**. A job shows `error`? → **T-22**.
6. Categorize "applied 0 / queued everything"? → **T-30**. Nothing auto-applies? → **T-31**.
7. Chat returns 503 / won't act? → **T-40**, **T-41**.
8. Can't edit provider settings (403)? → **T-50**.

---

## Provider setup

### T-01 — No AI provider configured
- **Symptom:** Chat returns HTTP **503** "No AI provider configured"; `POST /jobs/<kind>` finishes with `status:"error"`, `error:"No AI provider configured…"`; enrichment does nothing.
- **Apps:** all.
- **Cause:** `AI_PROVIDER` (HomeHoard/myMeal) or `llm_provider` (Edibl) is blank.
- **Fix:** Set a provider in the UI — HomeHoard **Tools → AI provider**, Edibl/myMeal **Settings** — or via the add-on option / env var (`<PREFIX>_AI_PROVIDER` = `ollama` | `openai` | `claude`; Edibl uses `<PREFIX>_LLM_PROVIDER`, and also accepts `anthropic`/`homeassistant`).
- **Verify:** `GET /settings/ai` (HomeHoard) shows a non-empty `provider`; re-run the job → `status:"done"`.

### T-02 — Provider selected but "not fully configured"
- **Symptom:** Job/chat error "provider '<x>' is selected but not fully configured (missing API key, host, or model)".
- **Apps:** all.
- **Cause:** The chosen provider is missing a required field: **openai/claude** need an API key; **ollama** needs a reachable host + model.
- **Fix:** Provide the missing field. OpenAI-compatible **local** servers usually need no key — set a **base URL** instead (see T-03). Claude/OpenAI hosted need `<PREFIX>_ANTHROPIC_API_KEY` / `<PREFIX>_OPENAI_API_KEY`. Ollama needs `<PREFIX>_OLLAMA_URL`/`_HOST` + a pulled model.
- **Verify:** `GET /settings/ai` shows `apiKeySet:true` (hosted) or a `baseUrl` (local); provider list marks it `available:true`.

---

## Local SLM (OpenAI-compatible)

### T-03 — Point the app at a local model server (LM Studio / vLLM / llama.cpp / LocalAI)
- **Symptom:** Want to use a local SLM but there's no "LM Studio" option.
- **Apps:** all.
- **Cause:** Local SLMs are reached through the **OpenAI-compatible** provider, not a dedicated option.
- **Fix:** Choose provider **`openai`** and set the **base URL** to the server's OpenAI endpoint (usually ends in `/v1`), plus the model name. Examples: LM Studio `http://<host>:1234/v1`, vLLM/llama.cpp `http://<host>:8000/v1`, Ollama's OpenAI shim `http://<host>:11434/v1`. Env: `<PREFIX>_OPENAI_BASE_URL` (Edibl: `<PREFIX>_LLM_BASE_URL`). A key is optional for most local servers.
- **Verify:** In HomeHoard's picker click **List models** — it should return the server's models. Then run a job.

### T-04 — Base URL rejected (422 "base URL host is not allowed")
- **Symptom:** Saving the provider base URL returns **422** "base URL host is not allowed" or "must be http or https".
- **Apps:** all (HomeHoard enforces on save + model probe; Edibl/myMeal accept any host).
- **Cause:** SSRF guard blocks **link-local / cloud-metadata** addresses (`169.254.x.x`, `fe80::`, IPv4-mapped equivalents) to stop the server being pointed at internal metadata endpoints.
- **Fix:** Use a normal loopback or LAN address (`http://localhost:1234/v1`, `http://192.168.x.x:1234/v1`) — those are allowed. Don't use `169.254.*`.
- **Verify:** Re-save → 200; provider becomes active.

### T-05 — Local server unreachable from the add-on container
- **Symptom:** Job errors with a connection/timeout; **List models** returns empty.
- **Apps:** all.
- **Cause:** The model server is bound to loopback (`127.0.0.1`) inside its own container/host, so the add-on container can't reach it; or wrong host/port.
- **Fix:** Bind the model server to `0.0.0.0` and use the host's LAN name/IP (not `localhost`, which is the *add-on's* localhost). For Ollama: start it with `OLLAMA_HOST=0.0.0.0`. Confirm the port. myMeal has `GET /ai/discover-ollama` to probe common Ollama addresses.
- **Verify:** `curl http://<host>:<port>/v1/models` from another machine returns data; **List models** populates.

---

## Enrichment & web search

### T-10 — Enrichment / "describe" / import-by-name finds nothing
- **Symptom:** "AI descriptions" job finishes with `described:0`; per-item Describe returns **409/422**; myMeal import-by-name returns **503**.
- **Apps:** HomeHoard (items), Edibl (products), myMeal (import-by-name).
- **Cause:** Web search is **Ollama-cloud-only** (`ollama.com`) and needs its **own** key, *separate from the generation provider*. Without the search key there's nothing to search — even if a local/OpenAI/Claude provider is set.
- **Fix:** Set the search key: `<PREFIX>_OLLAMA_SEARCH_KEY` (an ollama.com API key). The generation provider (which writes the description) can be anything; the *search* half always uses this key.
- **Verify:** `GET /settings/ai` shows `hasSearchKey:true` (HomeHoard); re-run → `described > 0` when results exist.

### T-11 — Enrichment writes a raw snippet instead of a clean description
- **Symptom:** Descriptions look like a copied web snippet, not synthesized prose.
- **Apps:** all.
- **Cause:** A search key is set (so web search works) but **no generation provider** is configured, so synthesis falls back to the top search snippet.
- **Fix:** Configure a provider (T-01). Then synthesis uses it.
- **Verify:** Re-run → descriptions read as 1–2 synthesized sentences + keywords.

---

## Background jobs & the worker

### T-20 — A job stays `pending` and never runs
- **Symptom:** `GET /jobs/<id>` stays `status:"pending"`; progress never moves.
- **Apps:** all.
- **Cause:** The background **worker poller** isn't running. It's disabled when `<PREFIX>_WORKER_ENABLED=false` (the default in the test suite) and when the app is imported without going through `create_app` (e.g. the MCP process).
- **Fix:** Ensure `<PREFIX>_WORKER_ENABLED` is unset/true (default). In production the add-on runs `gunicorn -w 2`, and each worker starts one poller. If you run a custom single-process dev server, the poller still starts as long as WORKER_ENABLED isn't false.
- **Verify:** The job moves to `running` then `done` within a few seconds; the log shows "job worker started".

### T-21 — "A run is already active" / second click does nothing
- **Symptom:** Clicking a job button again returns the same job (HTTP **202**) instead of starting a new one.
- **Apps:** all.
- **Cause:** By design there is **one active job per household + kind** (enforced by a partial-unique index). Re-enqueuing resumes the existing job.
- **Fix:** Wait for the active job to finish, then run again. This is expected, not an error.
- **Verify:** `GET /jobs?kind=<kind>` shows a single active job.

### T-22 — Job shows `status:"error"`
- **Symptom:** `GET /jobs/<id>` → `status:"error"` with an `error` message.
- **Apps:** all.
- **Cause:** Usually provider unavailability (T-01/T-02) surfaced at run time, or "Web search isn't configured" for an enrich job (T-10). Per-item model failures are swallowed (best-effort) and do **not** error the whole job.
- **Fix:** Read `error`, then apply the matching fix above.
- **Verify:** Re-run → `status:"done"`.

### T-23 — A long job appears to run twice / duplicates work
- **Symptom:** Suspicion that a long-running job restarted.
- **Apps:** all.
- **Cause:** The stale-job reaper requeues a job stuck in `running` for >20 min with **no progress heartbeat** (assumed dead worker). A *live* job heartbeats each item and is never reaped.
- **Fix:** None needed if the job is progressing. If a worker was actually killed mid-run, the requeue is correct recovery.
- **Verify:** `updated_at` / `done` on the job advance while it runs.

---

## Auto-categorize, cluster & review

### T-30 — Categorize applied 0, queued everything (or queued a lot)
- **Symptom:** Categorize result `applied:0, queued:N`; items sit in **Review**.
- **Apps:** all.
- **Cause:** This is the **confidence gate** working as designed. A label/tag/category is auto-applied **only** when (a) the model's confidence ≥ threshold **and** (b) it matches something that already exists (an existing label/tag; a known Edibl category). New labels/tags are **never** auto-created, and low-confidence guesses always go to review.
- **Fix:** Nothing is broken — review the queue and accept the good ones (your accept/reject choices train later runs). To auto-apply more, either lower `<PREFIX>_AI_CONFIDENCE_THRESHOLD` (default `0.8`, range 0–1) or pre-create the labels/tags you expect so matches can auto-apply.
- **Verify:** Lower the threshold and re-run → `applied` rises for confident, existing-label matches.

### T-31 — Nothing ever auto-applies, even obvious matches
- **Symptom:** Even clearly-correct labels always land in review.
- **Apps:** all (myMeal tags, HomeHoard labels, Edibl categories).
- **Cause:** The proposed label/tag doesn't yet exist (new → always review), or (Edibl) the proposed category isn't in the built-in `CATEGORIES` set, or the threshold is too high.
- **Fix:** Accept a few from the review queue to create the tags/labels; subsequent runs can then auto-apply matches. For Edibl, only canonical categories auto-apply (multi-word names are normalized, e.g. "dry goods" → "dry_goods"); anything else queues. Optionally lower the threshold.
- **Verify:** After the tag/label exists, re-run → confident matches auto-apply.

### T-32 — Edibl: an item keeps getting re-scanned but nothing changes
- **Symptom:** Same Edibl product re-processed on every categorize run.
- **Apps:** Edibl.
- **Cause:** The model can only return `"other"` for it. `"other"` is Edibl's "uncategorized" sentinel and is **not** treated as a real categorization (so it's skipped, not applied). The product stays `category:"other"` and is eligible next run.
- **Fix:** Expected — the AI genuinely can't categorize it. Set the category by hand, or add a *note* on the run to steer it. (This no longer accumulates duplicate review rows.)
- **Verify:** Set a real category by hand → the product drops out of the categorize set.

### T-33 — Review queue fills with duplicates of the same item
- **Symptom:** The same item appears many times in **Review** after several runs.
- **Apps:** all — should NOT happen on current versions.
- **Cause:** A fixed bug where re-runs re-queued items that already had a pending suggestion.
- **Fix:** Update to the current version; re-runs now skip items with a pending suggestion. Reject the duplicates once.
- **Verify:** Run categorize twice → the pending count doesn't grow for already-queued items.

### T-34 — A per-run note or model override "did nothing"
- **Symptom:** Setting the Note/Model fields on "AI organize" (or the enrich note/model on HomeHoard) had no visible effect.
- **Apps:** all.
- **Cause:** The note steers the prompt (subtle) and the model override only changes which model the **current provider** uses — it does **not** switch providers. Blank fields are ignored.
- **Fix:** Enter a model the configured provider actually serves. To change providers, use the provider picker, not the per-run model field.
- **Verify:** Job `params` echo the note/model (`GET /jobs/<id>` → `params`).

### T-35 — Accepting a cluster/family labels the wrong or too few items
- **Symptom:** After "Accept & group/label", some expected members weren't tagged.
- **Apps:** all.
- **Cause:** Members are re-checked at accept time and any that were deleted or belong to another household are dropped; clusters with fewer than 2 valid members are never proposed.
- **Fix:** Expected safety behavior. Re-run cluster if the collection has changed.
- **Verify:** The accept response reports `applied:<count>` of members actually tagged.

---

## Chat assistant

### T-40 — Chat returns 503 "No AI provider configured"
- **Symptom:** Chat panel shows a setup message or 503.
- **Apps:** HomeHoard, Edibl, myMeal (all have chat).
- **Cause:** Same as **T-01**.
- **Fix:** Configure a provider.
- **Verify:** Chat answers.

### T-41 — Chat answers but never looks anything up / won't act
- **Symptom:** Replies are generic; it doesn't call tools (search inventory, add stock, etc.).
- **Apps:** all.
- **Cause:** The selected model isn't **tool-calling capable** (common with small Ollama models). The loop degrades to plain answers.
- **Fix:** Use a tool-capable model (recent Llama/Qwen tool variants, or a hosted OpenAI/Claude model). Edibl note: the `homeassistant` provider is completion-only and cannot use tools by design.
- **Verify:** Ask "where is my drill?" (HomeHoard) — it should return a real location from your data.

---

## Provider config permissions & platform

### T-50 — Can't edit the AI provider (403 "instance admin privileges required")
- **Symptom:** `GET/PUT /settings/ai` returns **403**; the provider card is hidden.
- **Apps:** HomeHoard.
- **Cause:** The AI provider config is **instance-wide** and editable only by the **founding household's owner** (the earliest-created group's owner), because it drives shared outbound calls. Edibl/myMeal store provider config **per household** instead.
- **Fix:** Sign in as the founding owner, or set the provider via the add-on options / env instead of the UI.
- **Verify:** As the founding owner, the AI provider card appears and saves.

### T-51 — Container crashes on startup with an httpx `proxies` TypeError
- **Symptom:** `TypeError: Client.__init__() got an unexpected keyword argument 'proxies'` when the OpenAI/Anthropic provider is first used.
- **Apps:** all.
- **Cause:** An old `openai`/`anthropic` SDK pinned below the httpx-0.28 compatibility floor.
- **Fix:** Rebuild against current requirements (`openai>=1.55.3`, `anthropic>=0.42.0`). A pure-Ollama install is unaffected (those SDKs are lazy-imported).
- **Verify:** Selecting OpenAI/Claude and running a job succeeds.

### T-52 — A saved API key can't be cleared / "Disabled" reverts to an env provider
- **Symptom:** Choosing "Disabled" or leaving a key blank doesn't stick.
- **Apps:** HomeHoard.
- **Cause:** Blank UI values fall back to the add-on/env config. Explicit disable and key-clear are supported but distinct actions.
- **Fix:** Use **Disabled** in the provider dropdown (it stores an explicit off that overrides env), and **Clear saved key** to remove a stored key. Re-entering a blank key never wipes a saved one (by design).
- **Verify:** `GET /settings/ai` reflects `provider:""` and `apiKeySet:false`.

---

## App reference

Substitute `<PREFIX>` and locations per app.

| | HomeHoard | Edibl | myMeal |
|---|---|---|---|
| Env prefix | `HBOX_` | `EDIBL_` | `MYMEAL_` |
| Provider config | **Tools → AI provider** (instance-admin, founding owner) | **Settings** / add-on options (per household) | **Settings** / add-on options (per household) |
| Provider var | `HBOX_AI_PROVIDER` | `EDIBL_LLM_PROVIDER` | `MYMEAL_AI_PROVIDER` |
| Providers | ollama, openai, claude | ollama, openai, anthropic, homeassistant | claude, openai, ollama, ollama_cloud |
| Base URL var | `HBOX_OPENAI_BASE_URL` | `EDIBL_LLM_BASE_URL` | `MYMEAL_OPENAI_BASE_URL` (`openai_base_url` add-on option) |
| Web-search key | `HBOX_OLLAMA_SEARCH_KEY` | `EDIBL_OLLAMA_SEARCH_KEY` | `MYMEAL_OLLAMA_SEARCH_KEY` |
| Confidence threshold | `HBOX_AI_CONFIDENCE_THRESHOLD` | `EDIBL_AI_CONFIDENCE_THRESHOLD` | `MYMEAL_AI_CONFIDENCE_THRESHOLD` |
| Worker toggle | `HBOX_WORKER_ENABLED` | `EDIBL_WORKER_ENABLED` | `MYMEAL_WORKER_ENABLED` |
| Chat | **Assistant** page | chat FAB (bottom-right) | chat widget |
| Bulk AI job(s) | `enrich`, `categorize`, `cluster` | `enrich`, `categorize`, `cluster` | `nutrition`, `categorize`, `cluster` |
| Categorize target | item labels (M2M) | product `category` (+ `family` for cluster) | recipe tags (M2M) |
| Review page | **Review** (Utilities nav) | **Review** (Utilities nav) | **Review** (nav) |

### Key invariants (so you don't chase non-bugs)
- Web search is **always** Ollama-cloud (`ollama.com`) and needs its own key, independent of the generation provider.
- New labels/tags are **never** auto-created; they always go to review.
- One active background job per household + kind; re-enqueue resumes it.
- Confidence threshold default is `0.8`; only existing labels/tags (and known Edibl categories) auto-apply.
- Provider/model overrides are per-run on organize/enrich only, and never switch providers.
