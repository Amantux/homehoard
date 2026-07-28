# Chat Interface Spec — v1

A normative, reusable contract for the chat assistant: its HTTP surface, streaming
protocol, tool and provider contracts, and — the part meant for reuse —
**connect-ability**: how the chat connects to LLM/SLM providers, to sibling apps'
tools, and to Home Assistant Assist / MCP clients.

This is a *contract* document (implement to it). For how it's built internally, see
[`chat-and-providers.md`](chat-and-providers.md). Keywords **MUST / SHOULD / MAY**
are normative (RFC 2119).

- **Spec version:** 1.0
- **Reference implementation:** HomeHoard (`Amantux/homehoard`); siblings Edibl,
  myMeal implement the same v1 contract with the path/port mapping in §11.

---

## 1. Transport & auth

- All endpoints are JSON over HTTP under a base path resolved **relative to the
  page** so the app works behind a Home Assistant **ingress** mount
  (`/api/hassio_ingress/<token>/api/v1`) and standalone (`/api/v1`). Clients MUST
  derive the base from their own URL, not hard-code `/api/v1`.
- **Auth:** a bearer token in the `Authorization` header (NOT a cookie). Behind
  ingress, HA authenticates the user and the app runs `disable_auth: true`, so no
  token is sent. A standalone deployment requires the header.
- Because auth is a header, **streaming MUST use `fetch` + a `ReadableStream`
  reader, never `EventSource`** (which cannot set headers).
- All chat state is **group-scoped**; a resource id belonging to another group MUST
  return `404`, never that resource.

---

## 2. Chat — request/response (`POST <chat>`)

Non-streaming turn.

**Request** `{"message": string, "sessionId"?: string}`
- `message` MUST be non-empty after trim, else `422`.
- Omit `sessionId` to start a new session; the server creates one titled from the
  message.

**Response** `200`
```json
{
  "sessionId": "string",
  "reply": "string",
  "actions": [ Action ],
  "message": ChatMessage
}
```

**Errors:** `422` empty message · `503` no provider configured · `502` provider
failed mid-turn (server MUST roll back so no phantom session remains) · `404`
unknown/foreign `sessionId` · `401` unauthenticated · `429` rate-limited.

Servers SHOULD rate-limit (reference: 30/min/user).

---

## 3. Chat — streaming (`POST <chat>/stream`)

Same semantics as §2 but the reply streams. **Opt-in** (see §7).

- **Media type:** `application/x-ndjson` — one JSON object per line (`\n`).
- Response headers MUST include `Cache-Control: no-cache` and
  `X-Accel-Buffering: no` (so ingress/nginx don't buffer).
- Pre-stream validation still applies: `422` empty message and `503` no provider
  MUST be returned as normal (non-streamed) responses **before** the stream starts.
  Failures *after* the stream has started MUST be delivered as an `error` event
  (the HTTP status is already `200`).

**Event schema** (server → client, one per line, in order):

| `type` | Fields | Meaning |
|---|---|---|
| `delta` | `text: string` | Append to the current assistant message |
| `tool` | `name: string` | A tool is running (advisory status; MAY be ignored) |
| `done` | `sessionId, reply, actions[], message` | Terminal success — identical payload to §2 |
| `error` | `error: string` | Terminal failure (human-readable, no stack) |

A conforming stream MUST end with exactly one `done` **or** one `error`. Clients
MUST treat `reply` in `done` as authoritative (it equals the concatenated deltas).
`actions` can only appear in `done` (they derive from the completed tool trace).

---

## 4. Sessions

- `GET  <chat>/sessions` → `{"items": [ChatSessionSummary]}` (most-recent first)
- `GET  <chat>/sessions/{id}` → `ChatSession` with `messages[]`
- `DELETE <chat>/sessions/{id}` → `204`

Edibl's chat is **stateless server-side** (the client sends the full `messages`
array each turn); it MAY omit the session endpoints. HomeHoard/myMeal persist.

---

## 5. Streaming default setting (`<settings>/chat`)

- `GET` (any member) → `{"stream": boolean}` — the household default.
- `PUT` (owner) `{"stream": boolean}` → echoes it.
- Default MUST be `false` (classic POST) until an owner opts in.

---

## 6. Actions & undo

A data-changing tool produces an **Action** for the UI:

```
Action = { "tool": string, "label"?: string, "result"?: object,
           "undo"?: UndoDescriptor }
```

- `undo` is present only when the result carries the ids needed to reverse it.
- `UndoDescriptor` is an **op-tagged object**, e.g. `{"op":"delete_lot","lotId":…}`.
- Reversible actions are undone via `POST <chat>/undo` with the descriptor. Some
  undos are client-side (a normal DELETE/PATCH); **cross-app** undos MUST be
  relayed server-side (§9). `404` on undo (already gone) SHOULD be treated as
  success.

---

## 7. Connect-ability I — LLM/SLM providers

The chat is provider-agnostic; connecting a model is configuration, not code.

- **Provider id** ∈ `{ollama, openai, claude}` (Edibl also `anthropic`,
  `homeassistant`; myMeal also `ollama_cloud`). Chosen by `<APP>_AI_PROVIDER` env /
  add-on option, or the in-app picker (the stored value wins).
- **Local SLM** (LM Studio, vLLM, llama.cpp, Ollama `/v1`): use provider `openai`
  and set a **base URL** to the server's OpenAI-compatible endpoint.
- **Provider contract** an adapter MUST implement:

  ```
  available() -> bool                         # has key/host/model
  complete_json(prompt, system?) -> dict       # one-shot structured output (prompt-for-JSON)
  chat(messages, system?, tools?) -> ChatResult
  chat_stream(messages, system?, tools?) -> iterator of
        {"type":"delta","text":str} ... {"type":"final","result":ChatResult}
  ```
  `ChatResult = {content: str, tool_calls: [ToolCall]}`;
  `ToolCall = {id, name, arguments: object}`.
- **Config resolution:** non-empty DB override **>** env default, stored
  **per-provider-namespaced** so switching providers never sends vendor A's secret
  to vendor B. A user-supplied **base URL MUST pass an SSRF guard** (reject
  link-local / cloud-metadata `169.254.*`, `fe80::`, IPv4-mapped; allow loopback +
  LAN).
- **Config scope** is an app choice: instance-global (HomeHoard, founding-owner
  only) or per-group (Edibl, myMeal).
- **Web search** (enrichment) is always Ollama-cloud and uses its own key,
  independent of the generation provider.

---

## 8. Connect-ability II — tool contract

Tools are how the chat *acts*. The schema is neutral (vendor-independent):

```
Tool = { "name": string, "description": string,
         "parameters": JSONSchema }      // object schema
```

Rules a conforming implementation MUST follow:
- Adapters translate `parameters` to each vendor's tool format; tool **results are
  fed back to the model as plain user-role text**, not vendor-native tool-result
  blocks — this keeps one executor + one schema working across all providers.
- Each tool executes group-scoped. A tool failure MUST be caught and fed back to
  the model as `{"error": …}` — it MUST NOT `500` the turn.
- Writes are staged (`flush` / SAVEPOINT); the **request owns a single commit**.
- Only the final (no-tool-call) model turn yields user-facing `reply` text.

---

## 9. Connect-ability III — sibling-app tool federation

Two apps can expose their tools to each other's chat, so one assistant spans both
(e.g. "what can I cook, and do we have eggs?").

**Discovery & auth**
- `GET /edibl/discover` (example: myMeal→Edibl) asks the HA **Supervisor** for the
  companion add-on and returns its internal URL. Because both run behind ingress,
  **no token is needed** — the internal network is trusted.
- `GET /edibl/status` tests reachability ("is it configured and reachable?").
- Standalone: the operator enters the sibling URL + an API token (stored
  server-side, never echoed).
- A typed client (`EdiblClient.from_settings()`) encapsulates the HTTP calls.

**Tool exposure (MUST):**
- Sibling tools are appended to the local `TOOLS` **only when the sibling is
  connected** (`connected()` probe); otherwise neither chat shows the other's
  tools and each app is fully standalone.
- Sibling tool calls run inside the **pre-final (non-streamed) tool rounds** as
  blocking HTTP calls to the sibling; they degrade to `{available: false}` on
  error rather than failing the turn.

**Cross-app undo (MUST):** an action taken on the sibling can't be reversed by the
browser, so its `UndoDescriptor` (e.g. `edibl_stock`, `edibl_shopping`,
`edibl_unconsume`) is relayed by the local server via `POST <chat>/undo`, which
calls the sibling client. Ids in relayed undos MUST be validated (reject `/`,
`..`).

---

## 10. Connect-ability IV — MCP / Home Assistant Assist

The **same tools** are exposed to HA Assist and any MCP client via a bundled MCP
server (SSE, `/sse`), so voice/other agents get the identical capability surface as
the in-app chat.

- Reachable on the add-on's **internal** container network by default (not
  published to the LAN). Add HA's *Model Context Protocol* client pointing at
  `http://<slug>-<app>:<port>/sse`.
- Ports: HomeHoard `7766`, Edibl `7767`, myMeal `7851`.
- Auth: required when hardened (`disable_auth: false`), when a static MCP token is
  set, or when a scoped MCP key is minted; otherwise open on the internal network.
- Note: an LLM-backed Assist pipeline needs a **tool-capable** model, same as the
  in-app chat — a non-tool model degrades to plain answers.

---

## 11. Per-app binding (paths, ports, scope)

| | `<chat>` | `<chat>/stream` | `<settings>/chat` | `<chat>/undo` | Provider scope | MCP |
|---|---|---|---|---|---|---|
| HomeHoard | `/chat` | `/chat/stream` | `/settings/chat` | — (display-only actions) | instance-global | `7766` |
| Edibl | `/assistant/chat` | `/assistant/chat/stream` | in `/assistant/config` + PUT | `/assistant/undo` | per-group | `7767` |
| myMeal | `/ai/chat` | `/ai/chat/stream` | `/settings/chat` (or `/ai/chat-pref`) | `/ai/chat/undo` | per-group | `7851` |

All under the app's `/api/v1` base. Providers: HomeHoard `{ollama,openai,claude}`;
Edibl `{ollama,openai,anthropic,homeassistant}`; myMeal
`{claude,openai,ollama,ollama_cloud}`.

---

## 12. Data types

```
ChatSession        = { id, title, updatedAt, messages: [ChatMessage] }
ChatSessionSummary = { id, title, updatedAt }
ChatMessage        = { id, role: "user"|"assistant", content, position,
                       toolTrace?: [TraceStep], createdAt }
TraceStep          = { tool: string, args: object, result: any }
Action             = { tool, label?, result?, undo?: UndoDescriptor }   // §6
UndoDescriptor     = { op: string, ... }                               // op-tagged
ToolCall           = { id, name, arguments: object }
ChatResult         = { content: string, tool_calls: [ToolCall] }
```

---

## 13. Conformance checklist

An implementation conforms to Chat Interface v1 if:

- [ ] `POST <chat>` returns `{sessionId, reply, actions, message}`; `422/503/502/404/401` per §2.
- [ ] `POST <chat>/stream` emits NDJSON `delta`/`tool` then exactly one `done`|`error`, with `X-Accel-Buffering: no`, and `422`/`503` are returned pre-stream.
- [ ] Streaming clients use `fetch`+ReadableStream (header auth), not `EventSource`.
- [ ] `GET/PUT <settings>/chat`; default `false`; per-browser override may layer on top.
- [ ] Provider adapters implement `available/complete_json/chat/chat_stream`; secrets are provider-namespaced; base URLs are SSRF-guarded.
- [ ] Tools use the neutral `{name,description,parameters}` schema; results fed back as text; a tool failure never `500`s the turn; single request commit.
- [ ] Sibling tools appear only when connected; cross-app undos relay server-side with id validation.
- [ ] The same tools are exposed over MCP/SSE for HA Assist.
- [ ] All chat state is group-scoped; foreign ids `404`.
