"""The HomeHoard conversational assistant.

Runs a provider-agnostic tool-calling loop: the model decides which tool to call,
we execute it against the group's inventory, feed the result back as text, and
repeat until the model answers. Feeding results back as plain text (rather than
each vendor's native tool-result block) keeps the loop identical across Ollama,
OpenAI, and Claude — the same tool schema and executor drive all three.
"""
from __future__ import annotations

import json

from ...extensions import db
from ...models import Item, Label, Location
from .base import AIProvider

SYSTEM = (
    "You are the HomeHoard assistant, a practical home-inventory helper. Help the "
    "user find their belongings, see where things are, and keep them organized. "
    "ALWAYS use the provided tools to look things up in the user's own inventory "
    "before answering — never invent items, locations, or labels they don't have. "
    "When you say where something is, name the location and bin. Keep answers short "
    "and useful."
)

TOOLS = [
    {
        "name": "search_items",
        "description": "Search the user's inventory by name/keyword (matches name, "
        "description, notes, brand, model, serial, barcode, and label). Returns "
        "matching items with where each one is.",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]},
    },
    {
        "name": "get_item",
        "description": "Get full details for one item by name or id: description, "
        "quantity, asset id, brand/model, labels, and every place it's stored.",
        "parameters": {"type": "object",
                       "properties": {"name_or_id": {"type": "string"}},
                       "required": ["name_or_id"]},
    },
    {
        "name": "where_is",
        "description": "List every place an item is stored (location, bin, quantity).",
        "parameters": {"type": "object",
                       "properties": {"name_or_id": {"type": "string"}},
                       "required": ["name_or_id"]},
    },
    {
        "name": "list_locations",
        "description": "List the user's storage locations (with their full path).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "list_labels",
        "description": "List the user's labels/tags.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "add_label_to_item",
        "description": "Attach an existing label to an item (both by name or id). "
        "Use only when the user asks to tag/label an item.",
        "parameters": {"type": "object",
                       "properties": {"item": {"type": "string"},
                                      "label": {"type": "string"}},
                       "required": ["item", "label"]},
    },
]

# Tools that change data — surfaced to the UI as actions taken this turn.
_WRITE_TOOLS = {"add_label_to_item"}


def _find_item(gid, name_or_id):
    it = db.session.get(Item, str(name_or_id))
    if it and it.group_id == gid:
        return it
    like = f"%{str(name_or_id).strip()}%"
    return (db.session.query(Item)
            .filter(Item.group_id == gid, Item.name.ilike(like))
            .order_by(Item.name.asc()).first())


def _find_label(gid, name_or_id):
    lb = db.session.get(Label, str(name_or_id))
    if lb and lb.group_id == gid:
        return lb
    like = f"%{str(name_or_id).strip()}%"
    return (db.session.query(Label)
            .filter(Label.group_id == gid, Label.name.ilike(like))
            .order_by(Label.name.asc()).first())


def _item_brief(gid, it) -> dict:
    from ...api.lookup import item_where  # local: api imports services
    return {
        "id": it.id, "name": it.name, "description": it.description or "",
        "quantity": it.quantity, "manufacturer": it.manufacturer or "",
        "modelNumber": it.model_number or "",
        "labels": [lb.name for lb in it.labels],
        "placements": [{"quantity": h.quantity,
                        "location": (h.location.name if h.location else None),
                        "bin": (h.bin.name if h.bin else None)} for h in it.holdings]
        or [{"quantity": it.quantity, "where": item_where(it)}],
    }


def execute_tool(gid: str, name: str, args: dict):
    """Run one tool against the group's data. Returns a JSON-serializable value."""
    if not isinstance(args, dict):
        args = {}

    if name == "search_items":
        from ...api.lookup import _search_items  # local: avoid api↔services cycle
        return _search_items(gid, (args.get("query") or "").strip(), 15)

    if name == "get_item":
        it = _find_item(gid, args.get("name_or_id", ""))
        return _item_brief(gid, it) if it else {"error": "no matching item"}

    if name == "where_is":
        it = _find_item(gid, args.get("name_or_id", ""))
        if not it:
            return {"error": "no matching item"}
        return {"name": it.name, "placements": _item_brief(gid, it)["placements"]}

    if name == "list_locations":
        rows = (db.session.query(Location).filter_by(group_id=gid)
                .order_by(Location.name.asc()).all())
        return [{"id": loc.id, "name": loc.name} for loc in rows]

    if name == "list_labels":
        rows = (db.session.query(Label).filter_by(group_id=gid)
                .order_by(Label.name.asc()).all())
        return [{"id": lb.id, "name": lb.name} for lb in rows]

    if name == "add_label_to_item":
        it = _find_item(gid, args.get("item", ""))
        lb = _find_label(gid, args.get("label", ""))
        if not it:
            return {"error": "no matching item"}
        if not lb:
            return {"error": "no matching label"}
        if lb not in it.labels:
            it.labels.append(lb)
            db.session.flush()  # stage only — the request owns the single commit
        return {"ok": True, "item": it.name, "label": lb.name}

    return {"error": f"unknown tool {name}"}


def actions_from_trace(trace: list[dict]) -> list[dict]:
    """The data-changing tool calls in a turn, for the UI to show what was done."""
    return [{"tool": t["tool"], "result": t.get("result")}
            for t in trace if t.get("tool") in _WRITE_TOOLS
            and isinstance(t.get("result"), dict) and t["result"].get("ok")]


def run_chat(gid: str, provider: AIProvider, history: list[dict],
             user_message: str, max_iters: int = 6) -> dict:
    """Drive one assistant turn (with tool use) and return the reply + trace.

    ``history`` is prior {role, content} messages. Returns
    ``{"reply": str, "trace": [ {tool, args, result}... ]}``.
    """
    messages = list(history) + [{"role": "user", "content": user_message}]
    trace: list[dict] = []

    for _ in range(max_iters):
        result = provider.chat(messages, system=SYSTEM, tools=TOOLS)
        if not result.tool_calls:
            return {"reply": result.content or "", "trace": trace}
        messages.append({"role": "assistant", "content": result.content or "(using tools)"})
        for call in result.tool_calls:
            # Each tool runs in a SAVEPOINT: a tool failure rolls back only its own
            # staged write, never the request's transaction (the flushed chat session
            # and prior tool writes survive; the request still owns the final commit).
            sp = db.session.begin_nested()
            try:
                output = execute_tool(gid, call.name, call.arguments)
                sp.commit()
            except Exception as exc:  # noqa: BLE001 - feed errors back, never 500
                sp.rollback()
                output = {"error": f"{call.name} failed: {exc}"}
            trace.append({"tool": call.name, "args": call.arguments, "result": output})
            messages.append({"role": "user", "content": (
                f"Result of {call.name}({json.dumps(call.arguments)}): "
                f"{json.dumps(output)}")})
    # Exhausted the loop — ask once more for a plain answer.
    final = provider.chat(messages, system=SYSTEM)
    return {"reply": final.content or "", "trace": trace}


def run_chat_stream(gid: str, provider: AIProvider, history: list[dict],
                    user_message: str, max_iters: int = 6):
    """Streaming variant of :func:`run_chat`.

    Yields events for the endpoint to forward to the client:
      * ``{"type": "delta", "text": str}`` — assistant text as it is generated
      * ``{"type": "tool", "name": str}`` — a tool is about to run (status)
      * ``{"type": "done", "reply": str, "trace": [...]}`` — terminal

    Every model turn streams live; a turn that also asks for tools has its (usually
    empty) preamble streamed, the tools executed under per-tool SAVEPOINTs exactly
    as in :func:`run_chat`, and the loop continues. The caller owns the single
    commit — this generator only ``flush``es tool writes.
    """
    messages = list(history) + [{"role": "user", "content": user_message}]
    trace: list[dict] = []

    def _consume_turn(use_tools: bool):
        result = None
        for ev in provider.chat_stream(messages, system=SYSTEM,
                                       tools=(TOOLS if use_tools else None)):
            if ev["type"] == "delta":
                if ev["text"]:
                    yield {"type": "delta", "text": ev["text"]}
            elif ev["type"] == "final":
                result = ev["result"]
        yield {"type": "_result", "result": result}

    for _ in range(max_iters):
        result = None
        for ev in _consume_turn(use_tools=True):
            if ev["type"] == "_result":
                result = ev["result"]
            else:
                yield ev
        if result is None or not result.tool_calls:
            yield {"type": "done", "reply": (result.content if result else ""), "trace": trace}
            return
        messages.append({"role": "assistant", "content": result.content or "(using tools)"})
        for call in result.tool_calls:
            yield {"type": "tool", "name": call.name}
            sp = db.session.begin_nested()
            try:
                output = execute_tool(gid, call.name, call.arguments)
                sp.commit()
            except Exception as exc:  # noqa: BLE001 - feed errors back, never 500
                sp.rollback()
                output = {"error": f"{call.name} failed: {exc}"}
            trace.append({"tool": call.name, "args": call.arguments, "result": output})
            messages.append({"role": "user", "content": (
                f"Result of {call.name}({json.dumps(call.arguments)}): "
                f"{json.dumps(output)}")})
    # Exhausted the loop — one more turn, no tools, still streamed.
    result = None
    for ev in _consume_turn(use_tools=False):
        if ev["type"] == "_result":
            result = ev["result"]
        else:
            yield ev
    yield {"type": "done", "reply": (result.content if result else ""), "trace": trace}
