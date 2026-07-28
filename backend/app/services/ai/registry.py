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


def provider_for(provider=None, model=None) -> AIProvider:
    """Build a provider for a single run with an optional provider/model override
    (falls back to the configured one). Raises ProviderError if unavailable."""
    eff = effective_for(provider, model)
    name = _configured_name(eff)
    if not name:
        raise ProviderError("No AI provider configured.")
    if name not in _REGISTRY:
        raise ProviderError(f"Unknown AI provider '{name}'.")
    p = _REGISTRY[name](eff)
    if not p.available():
        raise ProviderError(f"AI provider '{name}' is not fully configured.")
    return p


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
