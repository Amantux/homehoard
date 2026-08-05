"""Provider selection.

The active provider and its config come from the effective settings: the global
``AppSetting`` overrides (set in the UI by the instance admin) layered over the
env / add-on defaults. ``list_providers`` powers the Settings UI.
"""
from __future__ import annotations

from .base import AIProvider, ProviderError
from .claude import ClaudeProvider
from .ollama import OllamaCloudProvider, OllamaProvider
from .openai import OpenAIProvider
from .provider_config import effective, effective_for

_REGISTRY: dict[str, type[AIProvider]] = {
    "ollama": OllamaProvider,
    "ollama_cloud": OllamaCloudProvider,
    "openai": OpenAIProvider,
    "claude": ClaudeProvider,
}


def _configured_name(eff) -> str:
    return (eff.AI_PROVIDER or "").strip().lower()


def get_provider(config=None) -> AIProvider:
    """Return the configured, available provider or raise ``ProviderError``.

    Not cached: config can change at runtime (a UI save) and must take effect on
    the next call.
    """
    eff = effective(config)
    name = _configured_name(eff)
    if not name:
        raise ProviderError(
            "No AI provider configured. Choose one in Tools → AI provider, or set "
            "HBOX_AI_PROVIDER (ollama, ollama_cloud, openai, or claude).")
    if name not in _REGISTRY:
        raise ProviderError(f"Unknown AI provider '{name}'.")
    provider = _REGISTRY[name](eff)
    if not provider.available():
        raise ProviderError(
            f"AI provider '{name}' is selected but not fully configured "
            "(missing API key, host, or model).")
    return provider


def get_provider_or_none(config=None) -> AIProvider | None:
    """The configured provider, or None when unset/unavailable (for best-effort
    tooling that degrades rather than erroring)."""
    try:
        return get_provider(config)
    except ProviderError:
        return None


def provider_for(provider=None, model=None, base_url=None, api_key=None) -> AIProvider:
    """Build a provider for a single run with an optional provider/model override
    (falls back to the configured one). ``base_url``/``api_key`` point the run at
    a different server — used by background jobs with their own SLM box.
    Raises ProviderError if unavailable."""
    eff = effective_for(provider, model, base_url=base_url, api_key=api_key)
    name = _configured_name(eff)
    if not name:
        raise ProviderError("No AI provider configured.")
    if name not in _REGISTRY:
        raise ProviderError(f"Unknown AI provider '{name}'.")
    p = _REGISTRY[name](eff)
    if not p.available():
        raise ProviderError(f"AI provider '{name}' is not fully configured.")
    return p


def resolve_job_provider(kind: str, opts: dict | None = None) -> AIProvider | None:
    """The provider override for a background job of ``kind`` (enrich / categorize /
    cluster), or None to fall back to the caller's default (the configured chat
    provider). Precedence: per-run ``opts`` (provider/model) > the stored async
    preference for this kind. Raises ``ProviderError`` if the chosen provider is
    unavailable."""
    from .provider_config import job_override
    from .url_guard import llm_url_ok

    opts = opts or {}
    pref = job_override(kind)
    provider = opts.get("provider") or pref["provider"]
    model = opts.get("model") or pref["model"]
    base_url = (opts.get("baseUrl") or pref["base_url"] or "").strip()
    api_key = opts.get("apiKey") or pref["api_key"]
    if not (provider or model or base_url or api_key):
        return None
    # Validated at the point of USE, not only where it was saved: this value can
    # also arrive through per-run opts, which never pass the settings guard.
    if base_url:
        ok, err = llm_url_ok(base_url)
        if not ok:
            raise ProviderError(f"the async AI server URL is not allowed: {err}")
    # Only pass the endpoint override when there IS one, so the common
    # provider/model-only call keeps its original shape — the same convention
    # this module already follows for provider=.
    extra = {}
    if base_url:
        extra["base_url"] = base_url
    if api_key:
        extra["api_key"] = api_key
    return provider_for(provider, model, **extra)


def list_providers(config=None) -> list[dict]:
    """Report every provider, whether it's available, and which is active."""
    eff = effective(config)
    active = _configured_name(eff)
    out = []
    for name, cls in _REGISTRY.items():
        try:
            avail = cls(eff).available()
        except Exception:  # noqa: BLE001 - never let a bad config crash the list
            avail = False
        out.append({"name": name, "available": avail, "active": name == active})
    return out
