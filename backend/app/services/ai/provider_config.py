"""AI-provider config: instance-global DB overrides on top of the env/add-on defaults.

Unlike the companion myMeal app (per-group), HomeHoard's AI provider is instance
infrastructure — it drives outbound calls (URL/key) shared by everyone — so it is
stored in the **global** ``AppSetting`` store and edited only by the founding-owner
"instance admin" (see ``api/misc._instance_admin_or_403``).

Storage is per-provider namespaced (``<provider>_<field>``) so one vendor's secret
is never sent to another vendor's endpoint when you switch providers. The Ollama
keys keep their original names (``ollama_url``/``ollama_model``/``ollama_search_key``)
for back-compat with the first-shipped card.

Precedence (per field): non-empty DB override  >  env / add-on default.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

from ..settings_store import get_overrides, set_values

_LOGGER = logging.getLogger(__name__)

VALID_PROVIDERS = ("", "ollama", "ollama_cloud", "openai", "claude")
SECRET_KEYS = frozenset({"ollama_api_key", "openai_api_key", "claude_api_key",
                         "ollama_search_key", "ollama_cloud_api_key"})
# Ollama's hosted cloud runs at a fixed host; the user supplies only a key + model.
OLLAMA_CLOUD_HOST = "https://ollama.com"


def _base(config) -> dict:
    """Env/add-on defaults for every AI attribute, from the app config."""
    g = config.get
    return {
        "AI_PROVIDER": (g("AI_PROVIDER") or ""),
        "OLLAMA_HOST": (g("OLLAMA_URL") or "http://localhost:11434"),
        "OLLAMA_MODEL": (g("OLLAMA_MODEL") or "llama3.1"),
        "OLLAMA_API_KEY": (g("OLLAMA_API_KEY") or ""),
        "OPENAI_BASE_URL": (g("OPENAI_BASE_URL") or ""),
        "OPENAI_MODEL": (g("OPENAI_MODEL") or "gpt-4o-mini"),
        "OPENAI_API_KEY": (g("OPENAI_API_KEY") or ""),
        "CLAUDE_MODEL": (g("CLAUDE_MODEL") or "claude-opus-4-8"),
        "ANTHROPIC_API_KEY": (g("ANTHROPIC_API_KEY") or ""),
        "AI_TIMEOUT_SECONDS": (g("AI_TIMEOUT_SECONDS") or 60),
        "OLLAMA_SEARCH_KEY": (g("OLLAMA_SEARCH_KEY") or ""),
        # Ollama Cloud — its own model + key, never the local Ollama's.
        "OLLAMA_CLOUD_MODEL": (g("OLLAMA_CLOUD_MODEL") or ""),
        "OLLAMA_CLOUD_API_KEY": (g("OLLAMA_CLOUD_API_KEY") or ""),
    }


def effective_settings(config, overrides) -> SimpleNamespace:
    """Env-derived settings with non-empty global DB overrides layered on top.

    ``config`` is a Flask ``current_app.config`` (or any ``.get`` mapping);
    ``overrides`` is ``settings_store.get_overrides()`` (non-blank stored values).
    """
    base = _base(config)

    def pick(okey, default):
        v = (overrides.get(okey) or "").strip()
        return v if v else default

    ns = SimpleNamespace(**base)
    # "off" is an explicit disable that overrides an env-set provider; a truly
    # absent override falls back to the env default.
    raw_provider = overrides.get("ai_provider")
    if raw_provider == "off":
        ns.AI_PROVIDER = ""
    else:
        ns.AI_PROVIDER = (raw_provider or base["AI_PROVIDER"] or "").strip().lower()
    ns.OLLAMA_HOST = pick("ollama_url", base["OLLAMA_HOST"])
    ns.OLLAMA_MODEL = pick("ollama_model", base["OLLAMA_MODEL"])
    ns.OLLAMA_API_KEY = pick("ollama_api_key", base["OLLAMA_API_KEY"])
    ns.OPENAI_BASE_URL = pick("openai_base_url", base["OPENAI_BASE_URL"])
    ns.OPENAI_MODEL = pick("openai_model", base["OPENAI_MODEL"])
    ns.OPENAI_API_KEY = pick("openai_api_key", base["OPENAI_API_KEY"])
    ns.CLAUDE_MODEL = pick("claude_model", base["CLAUDE_MODEL"])
    ns.ANTHROPIC_API_KEY = pick("claude_api_key", base["ANTHROPIC_API_KEY"])
    ns.OLLAMA_SEARCH_KEY = pick("ollama_search_key", base["OLLAMA_SEARCH_KEY"])
    # Ollama Cloud (ollama.com): fixed host, its own model + key (kept separate from
    # a local Ollama so switching between them never mixes credentials).
    ns.OLLAMA_CLOUD_HOST = OLLAMA_CLOUD_HOST
    ns.OLLAMA_CLOUD_MODEL = pick("ollama_cloud_model", base["OLLAMA_CLOUD_MODEL"])
    ns.OLLAMA_CLOUD_API_KEY = pick("ollama_cloud_api_key", base["OLLAMA_CLOUD_API_KEY"])
    return ns


def effective(config=None) -> SimpleNamespace:
    """The current effective config in an app/request context."""
    from flask import current_app
    cfg = config if config is not None else current_app.config
    return effective_settings(cfg, get_overrides())


def effective_for(provider=None, model=None, config=None) -> SimpleNamespace:
    """The effective config with a one-off provider/model override for a single run
    (e.g. a background job). Every provider's saved credentials are already resolved
    on the namespace, so switching the active provider still uses its stored key/URL;
    ``model`` overrides only the chosen provider's model."""
    eff = effective(config)
    if provider:
        eff.AI_PROVIDER = provider.strip().lower()
    if model:
        attr = {"ollama": "OLLAMA_MODEL", "openai": "OPENAI_MODEL",
                "claude": "CLAUDE_MODEL", "ollama_cloud": "OLLAMA_CLOUD_MODEL"}.get(eff.AI_PROVIDER)
        if attr:
            setattr(eff, attr, model.strip())
    return eff


# --- async-job AI preference ---------------------------------------------
def job_preference(kind: str) -> tuple[str | None, str | None]:
    """Stored async default ``(provider, model)`` for a background job. ``enrich``
    has its own preference; the organize jobs (``categorize`` / ``cluster``) share
    the ``organize`` preference. Either element is None when unset (→ same as the
    interactive chat provider)."""
    prefix = "enrich" if kind == "enrich" else "organize"
    over = get_overrides()
    return (over.get(f"{prefix}_provider") or None, over.get(f"{prefix}_model") or None)


# --- writes ---------------------------------------------------------------
def _pkey(provider: str, field: str) -> str:
    # Ollama keeps its original (un-prefixed style) names for back-compat.
    if provider == "ollama":
        return {"base_url": "ollama_url", "model": "ollama_model",
                "api_key": "ollama_api_key"}[field]
    return f"{provider}_{field}"


def set_overrides(provider=None, base_url=None, model=None, api_key=None,
                  search_key=None, clear_api_key=False) -> None:
    """Upsert overrides for the ACTIVE provider (or ``provider`` if given).

    A field left None is untouched; base_url/model '' clears it (falls back to
    env); api_key is written only when non-empty (re-saving a form that never gets
    the key back won't wipe it) unless ``clear_api_key``. Selecting Disabled
    (provider '') stores the ``off`` sentinel so it overrides an env-set provider.
    ``search_key`` is the Ollama-cloud web-search key (enrichment), independent of
    the generation provider.
    """
    pairs: dict[str, str] = {}
    disabling = provider is not None and not provider.strip()
    if provider is not None:
        pairs["ai_provider"] = provider.strip() or "off"
    # Field writes belong to the provider being set (or the current active one).
    # When disabling we touch no per-provider fields — they stay put, unused.
    if disabling:
        target = ""
    else:
        stored = get_overrides().get("ai_provider") or ""
        target = (provider.strip() if provider is not None else "") or \
            ("" if stored == "off" else stored)
    if target in ("ollama", "ollama_cloud", "openai", "claude"):
        # claude and ollama_cloud have no editable base URL (hosted / pinned host).
        if base_url is not None and target not in ("claude", "ollama_cloud"):
            pairs[_pkey(target, "base_url")] = base_url.strip()
        if model is not None:
            pairs[_pkey(target, "model")] = model.strip()
        if clear_api_key:
            pairs[_pkey(target, "api_key")] = ""
        elif api_key:
            pairs[_pkey(target, "api_key")] = api_key
    if search_key:
        pairs["ollama_search_key"] = search_key
    if pairs:
        set_values(pairs)


# --- reads for the UI -----------------------------------------------------
def _active_view(eff) -> dict:
    p = eff.AI_PROVIDER
    if p == "ollama":
        return {"baseUrl": eff.OLLAMA_HOST, "model": eff.OLLAMA_MODEL,
                "apiKeySet": bool(eff.OLLAMA_API_KEY)}
    if p == "ollama_cloud":
        return {"baseUrl": "", "model": eff.OLLAMA_CLOUD_MODEL,
                "apiKeySet": bool(eff.OLLAMA_CLOUD_API_KEY)}
    if p == "openai":
        return {"baseUrl": eff.OPENAI_BASE_URL, "model": eff.OPENAI_MODEL,
                "apiKeySet": bool(eff.OPENAI_API_KEY)}
    if p == "claude":
        return {"baseUrl": "", "model": eff.CLAUDE_MODEL,
                "apiKeySet": bool(eff.ANTHROPIC_API_KEY)}
    return {"baseUrl": "", "model": "", "apiKeySet": False}


def settings_view(config=None) -> dict:
    """Redacted, UI-facing view of the effective AI config. No secret values."""
    eff = effective(config)
    return {"provider": eff.AI_PROVIDER, **_active_view(eff),
            "validProviders": [p for p in VALID_PROVIDERS if p],
            "hasSearchKey": bool(eff.OLLAMA_SEARCH_KEY)}


def probe_config(config=None, provider=None, base_url=None, api_key=None) -> SimpleNamespace:
    """A throwaway effective config from the values in the form (not yet saved),
    for a model-list probe. Falls back to the saved/env effective config."""
    eff = effective(config)
    p = (provider or eff.AI_PROVIDER or "").strip()
    eff.AI_PROVIDER = p
    if p == "ollama":
        if base_url:
            eff.OLLAMA_HOST = base_url.strip()
        if api_key:
            eff.OLLAMA_API_KEY = api_key
    elif p == "ollama_cloud":
        # Host is pinned; the cloud needs the key to list models.
        if api_key:
            eff.OLLAMA_CLOUD_API_KEY = api_key
    elif p == "openai":
        if base_url:
            eff.OPENAI_BASE_URL = base_url.strip()
        if api_key:
            eff.OPENAI_API_KEY = api_key
    return eff


def list_models(eff, timeout: float = 12.0) -> list[str]:
    """Query the active provider for its model list, for the UI picker.
    Best-effort; returns [] on any error (never raises into a request)."""
    import httpx

    from .url_guard import llm_url_ok

    p = eff.AI_PROVIDER
    # Resolve the base URL and validate it BEFORE constructing any HTTP client,
    # so an unsafe URL provably never reaches the network layer (and a test can
    # assert the request was never attempted). Validating at the point of USE
    # matters because a base URL from env / the add-on option never passes
    # through the /settings/ai guard. Loopback + private LAN stay allowed so a
    # self-hosted Ollama works; link-local (cloud metadata) does not.
    if p == "ollama":
        base_url = (eff.OLLAMA_HOST or "").rstrip("/")
    elif p == "ollama_cloud":
        base_url = (eff.OLLAMA_CLOUD_HOST or "").rstrip("/")
    elif p == "openai":
        base_url = (eff.OPENAI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    else:
        # claude has no list endpoint; the UI falls back to a free-text field.
        return []
    ok, err = llm_url_ok(base_url)
    if not ok:
        _LOGGER.warning("refusing to list models: %s", err)
        return []

    try:
        with httpx.Client(timeout=timeout) as c:
            if p == "ollama":
                h = {"Authorization": f"Bearer {eff.OLLAMA_API_KEY}"} if eff.OLLAMA_API_KEY else {}
                r = c.get(f"{base_url}/api/tags", headers=h)
                r.raise_for_status()
                return sorted(m.get("name", "") for m in r.json().get("models", []) if m.get("name"))
            if p == "ollama_cloud":
                h = {"Authorization": f"Bearer {eff.OLLAMA_CLOUD_API_KEY}"} if eff.OLLAMA_CLOUD_API_KEY else {}
                r = c.get(f"{base_url}/api/tags", headers=h)
                r.raise_for_status()
                return sorted(m.get("name", "") for m in r.json().get("models", []) if m.get("name"))
            h = {"Authorization": f"Bearer {eff.OPENAI_API_KEY}"} if eff.OPENAI_API_KEY else {}
            r = c.get(f"{base_url}/models", headers=h)
            r.raise_for_status()
            return sorted(m.get("id", "") for m in r.json().get("data", []) if m.get("id"))
    except Exception:  # noqa: BLE001 - a model-picker failure must not 500
        return []
