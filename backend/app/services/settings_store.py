"""Instance-global settings overrides (UI-editable), layered over the add-on/env
config. Holds the AI-provider settings that chat + tooling use — a stored value
wins over the add-on config; blank falls back to it. Per-provider namespaced so a
secret for one vendor never reaches another's endpoint (see services/ai/provider_config).
"""
from ..extensions import db
from ..models import AppSetting

AI_KEYS = (
    "ai_provider",
    # Ollama (original names kept for back-compat with the first-shipped card)
    "ollama_url", "ollama_model", "ollama_api_key", "ollama_search_key",
    # Ollama Cloud (ollama.com) — its own model + key; host is pinned.
    "ollama_cloud_model", "ollama_cloud_api_key",
    # OpenAI-compatible
    "openai_base_url", "openai_model", "openai_api_key",
    # Anthropic Claude
    "claude_model", "claude_api_key",
    # Chat UX: household default for streaming responses ("true"/"false").
    "chat_streaming",
    # Async-job AI preference: a provider+model default for background work,
    # separate from the interactive chat provider. "enrich" = enrichment jobs;
    # "organize" = the categorize + cluster jobs. Blank provider = same as chat.
    "enrich_provider", "enrich_model",
    "organize_provider", "organize_model",
)


def get_overrides() -> dict:
    """Stored non-blank overrides as {key: value}. Empty on any DB issue."""
    try:
        return {s.key: s.value for s in db.session.query(AppSetting).all() if s.value}
    except Exception:  # noqa: BLE001 - best-effort; never break a read path
        return {}


def set_values(pairs: dict) -> None:
    """Upsert the given AI overrides (only recognized AI_KEYS are stored)."""
    for key, value in pairs.items():
        if key not in AI_KEYS:
            continue
        row = db.session.get(AppSetting, key)
        if row is None:
            db.session.add(AppSetting(key=key, value=value or ""))
        else:
            row.value = value or ""
    db.session.commit()
