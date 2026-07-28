# Chat + AI providers — architecture & reuse guide

How the chat assistant and the pluggable LLM/SLM provider layer are wired, written
so the structure can be lifted into a new project. HomeHoard is the reference
implementation; the same shape ships in the sibling apps (Edibl, myMeal) with two
documented variations (per-group vs instance-global config; Edibl's self-contained
provider module).

Everything here is provider-agnostic: the app code never imports a vendor SDK
directly. Swapping Ollama ↔ OpenAI-compatible ↔ Claude is a config change.

---

## 1. The layers at a glance

```
UI (Chat.vue) ──POST /chat or /chat/stream──▶ api/chat.py (endpoint: session + commit)
                                                     │
                                                     ▼
                                        services/ai/agent.py
                                        run_chat / run_chat_stream
                                        (tool loop: model ↔ execute_tool)
                                                     │  provider.chat / chat_stream
                                                     ▼
                                        services/ai/registry.py  ──▶  provider_config.py
                                        get_provider()               (env + DB overrides,
                                                     │                 SSRF guard)
                          ┌──────────────────────────┼──────────────────────────┐
                          ▼                          ▼                          ▼
                   ollama.py                  openai.py                   claude.py
              (AIProvider adapters: available / _complete / chat / chat_stream)
```

Two operations cover every AI feature:
- **`complete_json`** — one-shot "return structured data" (enrichment, categorize,
  cluster). Portable by *prompting for JSON and parsing*, never a vendor's
  structured-output API.
- **`chat` / `chat_stream`** — a conversational turn with optional tool-calling.

---

## 2. The provider interface (`services/ai/base.py`)

```python
@dataclass
class ToolCall:      id: str; name: str; arguments: dict
@dataclass
class ChatResult:    content: str = ""; tool_calls: list[ToolCall] = []

class AIProvider(ABC):
    name: str
    def available(self) -> bool: ...                     # has key/host/model?
    def _complete(self, system, prompt, max_tokens) -> str: ...
    def chat(self, messages, system="", tools=None, max_tokens=2048) -> ChatResult: ...
    def chat_stream(self, messages, system="", tools=None, max_tokens=2048): ...  # generator
    def complete_json(self, prompt, system="", max_tokens=4096) -> dict:          # uses _complete + extract_json
```

- **`tools`** uses a neutral schema `[{name, description, parameters}]` where
  `parameters` is JSON-Schema. Each adapter translates to its own wire format.
- **`ChatResult`** is the normalized return: text plus a provider-agnostic list of
  `ToolCall`. The agent loop only ever sees this — it has zero vendor knowledge.
- **`extract_json`** tolerates ```` ```json ```` fences and prose, and raises
  `ProviderError` on anything that isn't a JSON object, so callers never defend
  against a non-dict.

### Adapter specifics (the only vendor-aware code)

| | tools out | tool calls parsed from | streaming |
|---|---|---|---|
| **Ollama** (`ollama.py`) | `{"type":"function","function":{name,description,parameters}}` | `message.tool_calls[i].function` (`arguments` already a dict) | `POST /api/chat` with `stream:true` → NDJSON lines, each `message.content` delta; tool calls arrive in the message object |
| **OpenAI** (`openai.py`) | same OpenAI function shape | `msg.tool_calls[].function` (`arguments` a **JSON string** → `json.loads`) | `stream=True` → `choices[0].delta.content`; tool-call args stream **fragmented by index** and must be concatenated before parsing |
| **Claude** (`claude.py`) | `{name, description, input_schema}`, `system` is a top-level param | `content` blocks of type `tool_use` (`input` is a dict) | `client.messages.stream(...)`: `text_stream` for deltas, `get_final_message()` for `tool_use` blocks |

SDKs (`openai`, `anthropic`) are **lazy-imported** inside `_get_client` so a
pure-Ollama install needs neither installed. Floors: `openai>=1.55.3`,
`anthropic>=0.42.0` (older `openai` passes a removed `proxies` kwarg to httpx 0.28
and crashes).

### `chat_stream` event protocol

`chat_stream` is a generator that yields, in order:
- `{"type": "delta", "text": str}` — zero or more, as text is generated
- exactly one terminal `{"type": "final", "result": ChatResult}` — full content + tool calls

`base.py` ships a **non-streaming fallback**: run the blocking `chat()`, emit its
whole content as one delta, then the final. Adapters override it with real token
streaming. This means "streaming works everywhere" even before an adapter has a
true streaming path.

---

## 3. Config resolution (`registry.py` + `provider_config.py`)

- **Precedence, per field:** non-empty DB override **>** env / add-on default.
- Storage is **per-provider namespaced** (`<provider>_<field>`) so one vendor's
  secret is never sent to another's endpoint when you switch providers.
- **`get_provider()`** resolves the effective config in a request, builds the
  active adapter, and raises `ProviderError` if none is configured or it isn't
  fully configured (missing key/host/model). **`provider_for_group(gid)`** builds a
  provider *outside* a request (background worker / MCP) by resolving that group's
  overrides explicitly.
- **SSRF guard** (`url_guard.llm_url_ok`) validates any user-supplied base URL:
  blocks link-local / cloud-metadata (169.254.x, IPv4-mapped, fe80::); allows
  loopback + LAN. Enforced on save and on the model-probe.

### The one variation to know

- **HomeHoard: instance-global** config (an `AppSetting` KV store), editable only
  by the founding-household owner — it drives shared outbound calls.
- **myMeal / Edibl: per-group** config — each household stores its own provider.
  myMeal uses a per-group override store (`settings_access`); Edibl uses UI
  overrides layered in `assistant._cfg()`. Chat + jobs are always per-group +
  `login_required`.

---

## 4. The agent tool loop (`services/ai/agent.py`)

```python
messages = history + [{"role":"user","content": user_message}]
for _ in range(max_iters):
    result = provider.chat(messages, system=SYSTEM, tools=TOOLS)
    if not result.tool_calls:
        return {"reply": result.content, "trace": trace}     # done
    messages.append({"role":"assistant","content": result.content or "(using tools)"})
    for call in result.tool_calls:
        sp = db.session.begin_nested()                        # SAVEPOINT per tool
        try:    output = execute_tool(gid, call.name, call.arguments); sp.commit()
        except: sp.rollback(); output = {"error": ...}        # feed the error back, never 500
        trace.append({...})
        messages.append({"role":"user","content": f"Result of {call.name}(...): {json(output)}"})
final = provider.chat(messages, system=SYSTEM)                # loop exhausted → force a plain answer
```

Design rules that make it robust and vendor-uniform:
- **Tool results are fed back as plain user-role text**, not each vendor's native
  tool-result block. One executor + one tool schema drive Ollama/OpenAI/Claude
  identically.
- **Only the final (no-tool) turn produces user-facing text.** Intermediate turns
  are tool-planning.
- **Transaction model:** tools only `flush()` (or run in a `begin_nested()`
  SAVEPOINT so one tool's failure can't poison the turn). **The request owns the
  single commit** — the endpoint commits once after the loop; a `ProviderError`
  rolls back so a failed turn leaves no phantom session.
- **`actions_from_trace(trace)`** extracts the data-changing tool calls for the UI
  to render "what was done" chips (and, where the result carries the ids, an undo).

The tool set is small and typed (`search_items`, `where_is`, `add_label_to_item`,
…). A cross-app integration (myMeal ↔ Edibl) appends extra tools only when the
sibling app is connected.

---

## 5. The chat endpoint (`api/chat.py`)

Non-streaming `POST /chat` (`login_required`, rate-limited):
1. Validate message (422 if empty); `get_provider()` (503 if unconfigured).
2. Load or create a group-scoped `ChatSession`; build `history` from its messages.
3. `run_chat(...)`; on `ProviderError` → `rollback()` + 502.
4. Append user + assistant `ChatMessage` (assistant stores `tool_trace`), bump
   `session.updated_at`, **one `commit()`**.
5. Return `{sessionId, reply, actions, message}`.

Cross-tenant safety: every session/message lookup filters by `current_group()`; a
foreign id is a 404, never a leak.

---

## 6. Streaming (`/chat/stream`, `run_chat_stream`)

Opt-in. Same tool loop, but the visible answer is streamed token-by-token.

### Transport
- **NDJSON over a normal `fetch` POST** (`application/x-ndjson`), one JSON object
  per line. **Not** Server-Sent Events / `EventSource` — auth is a bearer token in
  the `Authorization` header, which `EventSource` cannot set. The client reads
  `response.body.getReader()` (`api.streamPost`).
- Response headers: `Cache-Control: no-cache` and **`X-Accel-Buffering: no`** so
  Home Assistant ingress / nginx don't buffer the stream. Wrap the generator in
  `stream_with_context` so the request context + `db.session` stay alive.

### Event protocol (server → client, one per line)
- `{"type":"delta","text": "..."}` — append to the current assistant bubble
- `{"type":"tool","name": "..."}` — a tool is running (optional status)
- `{"type":"done", sessionId, reply, actions, message}` — terminal success
- `{"type":"error","error": "..."}` — terminal failure

`run_chat_stream` streams **every** model turn via `provider.chat_stream`; a turn
that also asks for tools has its (usually empty) preamble streamed, tools execute
under the same SAVEPOINTs, and the loop continues. `actions` derive from the full
trace, so they can only ship in the terminal `done` frame — after all tool rounds.

### The one bug worth pinning: writes must live inside the generator
Because the streamed generator runs after the view returns, **do every DB write —
creating the session, persisting messages, the commit — *inside* the generator**,
not in the view. Flushing a new `ChatSession` in the view and inserting its child
messages later from the generator throws a `FOREIGN KEY constraint failed`: the
session row isn't durably present when the child insert runs. Validate an existing
`sessionId` (404) and read its history in the view; **create** a new session inside
the generator. The single-commit / rollback-on-error model is otherwise identical
to the non-streaming path.

### Deployment caveat
The app runs `gunicorn -w 2` (sync workers; myMeal adds `--threads`). A streaming
turn holds one worker/thread for its whole duration, so N concurrent streams
saturate at the worker/thread count — fine at single-household concurrency, worth a
worker-class bump (`gthread`/`gevent`) if streaming becomes the primary path. Keep
turns bounded by `AI_TIMEOUT_SECONDS` and `max_iters`; incremental writes keep the
socket active so sync workers don't hit the request timeout mid-stream.

---

## 7. Stream vs. POST is a user choice

Two levels, so a household can set a default and any device can override:

```
effective_streaming = localStorage[<app>_chat_stream]   // per-browser override ('true'|'false')
                   ?? householdDefault                  // backend GET /settings/chat  (owner-set)
                   ?? false                              // default: classic POST
```

- **Per-browser override:** a toggle in the chat header writes localStorage.
  Appropriate because streaming reliability depends on the device / proxy / network.
- **Household default:** `GET /settings/chat` (any member) / `PUT` (owner), stored
  in the settings KV / per-group store. Set on the Settings/Tools page. **Defaults
  to classic POST** (no worker held open until someone opts in).

The frontend just picks the endpoint: streaming → `streamPost('/chat/stream', …)`
and live-append deltas; otherwise the existing `api.post('/chat', …)`.

---

## 8. Reuse checklist (adding this to a new app)

1. **Provider layer** — copy `services/ai/{base,registry,provider_config,url_guard,
   ollama,openai,claude}.py`. Decide instance-global vs per-group config and wire
   `get_provider()` / `provider_for_group()` accordingly.
2. **Config** — env vars `<APP>_AI_PROVIDER`, per-provider keys/models/base URLs,
   `<APP>_AI_TIMEOUT_SECONDS`; add a UI provider picker (provider select, base URL,
   model + live model probe, write-only key). SSRF-guard the base URL.
3. **Tool loop** — define a small neutral `TOOLS` schema + one `execute_tool`
   dispatcher over your domain; feed results back as text; tools flush, endpoint
   commits once; add `actions_from_trace`.
4. **Endpoints** — `POST /chat` (session + single commit) and, for streaming,
   `POST /chat/stream` (NDJSON, `stream_with_context`, `X-Accel-Buffering: no`,
   **all writes inside the generator**) + `GET/PUT /settings/chat`.
5. **Frontend** — a chat view; `api.streamPost` (fetch + ReadableStream, keep the
   auth header); the per-browser toggle + household-default precedence above.
6. **Tests** — a fake provider (a turn that returns a tool call, then an answer)
   exercises the real loop; a fake **streaming** provider (deltas + final) exercises
   `/chat/stream`; assert the terminal `done`, persistence, auth (401), and no
   secret leakage anywhere the report/telemetry surfaces touch.

Never send secrets to the wrong endpoint (namespace per provider), never let a
tool failure 500 the turn (feed it back), and never trust a user base URL (SSRF
guard). Those three are where the bodies are buried.
