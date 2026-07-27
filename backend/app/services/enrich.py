"""AI-enriched, searchable item descriptions.

Given an item's identifying fields, search the web (Ollama's hosted web search)
and synthesize a short factual description + keywords with the configured AI
provider (Ollama / OpenAI-compatible / Claude) so search finds the item by what it
actually is. Bounded and best-effort — it never raises to the caller (returns None
when search is off or finds nothing).

Web search is Ollama-cloud-specific (POST https://ollama.com/api/web_search with
``Authorization: Bearer <OLLAMA_SEARCH_KEY>`` -> {"results":[{title,url,content}]}),
keyed independently of the generation provider. Synthesis routes through
``services.ai.get_provider`` so it honors whatever LLM/SLM is wired up.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from .ai.provider_config import effective
from .ai.registry import get_provider_or_none

_LOGGER = logging.getLogger("homehoard.enrich")
_SEARCH_URL = "https://ollama.com/api/web_search"
_TIMEOUT = 20.0
# Barcode-aggregator/listing hosts — real product pages should rank ahead of these.
_AGGREGATOR_HOSTS = ("barcodelookup", "upcitemdb", "barcodespider", "go-upc",
                     "upcdatabase", "ean-search", "buycott", "barcode-list")


def search_key() -> str:
    """The Ollama-cloud web-search key (independent of the generation provider)."""
    return (effective().OLLAMA_SEARCH_KEY or "").strip()


def enabled() -> bool:
    """Enrichment needs the web-search key; without it there's nothing to search."""
    return bool(search_key())


def web_search(query, *, key=None, max_results=3):
    """Ollama hosted web search. Returns a list of {title,url,content}, or []."""
    key = key if key is not None else search_key()
    if not key:
        return []
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


def _snippets(results) -> str:
    return "\n\n".join(f"{r.get('title', '')}\n{r.get('content', '')}"[:600]
                       for r in results[:3])


def _synthesize(fields, results):
    """Turn search results into {description, keywords}. Uses the configured AI
    provider; falls back to a trimmed top-result snippet when none is available."""
    name = fields.get("name") or "this item"
    provider = get_provider_or_none()
    if provider is not None:
        prompt = (f"From the web results below, write a concise factual description of "
                  f"'{name}' (1-2 sentences) and 6-10 search keywords. Respond ONLY as "
                  f'JSON: {{"description": "...", "keywords": ["..."]}}.\n\n{_snippets(results)}')
        try:
            data = provider.complete_json(prompt)
            desc = (data.get("description") or "").strip()
            kws = [str(k).strip() for k in (data.get("keywords") or []) if k]
            if desc:
                return {"description": desc, "keywords": kws}
        except Exception as exc:  # noqa: BLE001 - fall back to raw snippet
            _LOGGER.info("model synthesis failed, using snippet: %s", exc)
    top = results[0] if results else {}
    return {"description": (top.get("content") or top.get("title") or "").strip()[:300],
            "keywords": []}


def rank_results(results):
    """Prefer retailer/manufacturer pages over barcode-aggregator listings (which
    have junk titles). Stable sort → aggregators sink, original order preserved."""
    def is_aggregator(r):
        host = (urlparse(r.get("url") or "").hostname or "").lower()
        return any(a in host for a in _AGGREGATOR_HOSTS)
    return sorted(results, key=is_aggregator)


def extract_product(results):
    """Identify the product from web-search results using the configured AI
    provider. Returns {name, brand} or None. Ranks results first and feeds titles +
    snippets, so it beats scraping a title."""
    ranked = rank_results(results)
    snippets = _snippets(ranked)
    provider = get_provider_or_none()
    if not snippets.strip() or provider is None:
        return None
    prompt = ('From the web results below, identify the single retail product. Respond '
              'ONLY as JSON: {"name": "<product name>", "brand": "<brand or empty>"}. '
              'If the results are only barcode-lookup pages with no real product, return '
              f'an empty name.\n\n{snippets}')
    try:
        data = provider.complete_json(prompt)
        name = (data.get("name") or "").strip()[:80]
        if name:
            return {"name": name, "brand": (data.get("brand") or "").strip()[:80]}
    except Exception as exc:  # noqa: BLE001 - best-effort; caller falls back
        _LOGGER.info("product extraction failed: %s", exc)
    return None


def describe(fields) -> dict | None:
    """Return {description, keywords, sources} for an item, or None when web search
    is not configured, there's nothing to search, or nothing was found."""
    if not enabled():
        return None
    query = _query(fields)
    if not query:
        return None
    results = web_search(query)
    if not results:
        return None
    out = _synthesize(fields, results)
    if not out.get("description"):
        return None
    out["sources"] = [r.get("url") for r in results[:3] if r.get("url")]
    return out
