"""AI-enriched, searchable item descriptions via Ollama's hosted web search.

Given an item's identifying fields, search the web and synthesize a short factual
description + keywords so search finds the item by what it actually is. Bounded
and best-effort — it never raises to the caller (returns None when search is off
or finds nothing).

Ollama web search: POST https://ollama.com/api/web_search with
`Authorization: Bearer <OLLAMA_API_KEY>` and {"query","max_results"} ->
{"results":[{"title","url","content"}]}.
"""
from __future__ import annotations

import json
import logging

import httpx
from flask import current_app

_LOGGER = logging.getLogger("homehoard.enrich")
_SEARCH_URL = "https://ollama.com/api/web_search"
_TIMEOUT = 20.0


def _cfg():
    c = current_app.config
    return {
        "key": (c.get("OLLAMA_SEARCH_KEY") or "").strip(),
        "url": (c.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/"),
        "model": (c.get("OLLAMA_MODEL") or "llama3.1").strip(),
    }


def enabled() -> bool:
    return bool(_cfg()["key"])


def web_search(query, *, key, max_results=3):
    """Ollama hosted web search. Returns a list of {title,url,content}, or []."""
    try:
        r = httpx.post(_SEARCH_URL, headers={"Authorization": f"Bearer {key}"},
                       json={"query": query, "max_results": max_results}, timeout=_TIMEOUT)
        r.raise_for_status()
        return (r.json() or {}).get("results") or []
    except Exception as exc:  # noqa: BLE001 - absence/network is the normal failure
        _LOGGER.info("web_search failed: %s", exc)
        return []


def _query(fields) -> str:
    parts = [fields.get(k) for k in ("manufacturer", "name", "model_number")]
    return " ".join(str(p).strip() for p in parts if p).strip()


def _synthesize(fields, results, cfg):
    """Turn search results into {description, keywords}. Uses the local Ollama
    model when reachable; otherwise falls back to a trimmed top-result snippet."""
    snippets = "\n\n".join(f"{r.get('title', '')}\n{r.get('content', '')}"[:600]
                           for r in results[:3])
    name = fields.get("name") or "this item"
    if cfg["model"] and cfg["url"]:
        prompt = (f"From the web results below, write a concise factual description of "
                  f"'{name}' (1-2 sentences) and 6-10 search keywords. Respond ONLY as "
                  f'JSON: {{"description": "...", "keywords": ["..."]}}.\n\n{snippets}')
        try:
            r = httpx.post(f"{cfg['url']}/api/generate",
                           json={"model": cfg["model"], "prompt": prompt,
                                 "stream": False, "format": "json"}, timeout=_TIMEOUT)
            r.raise_for_status()
            data = json.loads((r.json() or {}).get("response") or "{}")
            desc = (data.get("description") or "").strip()
            kws = [str(k).strip() for k in (data.get("keywords") or []) if k]
            if desc:
                return {"description": desc, "keywords": kws}
        except Exception as exc:  # noqa: BLE001 - fall back to raw snippet
            _LOGGER.info("model synthesis failed, using snippet: %s", exc)
    top = results[0] if results else {}
    return {"description": (top.get("content") or top.get("title") or "").strip()[:300],
            "keywords": []}


def describe(fields) -> dict | None:
    """Return {description, keywords, sources} for an item, or None when web search
    is not configured, there's nothing to search, or nothing was found."""
    cfg = _cfg()
    if not cfg["key"]:
        return None
    query = _query(fields)
    if not query:
        return None
    results = web_search(query, key=cfg["key"])
    if not results:
        return None
    out = _synthesize(fields, results, cfg)
    if not out.get("description"):
        return None
    out["sources"] = [r.get("url") for r in results[:3] if r.get("url")]
    return out
