"""Instance-global settings overrides (UI-editable), layered over the add-on/env
config. Currently the Ollama AI settings that enrichment + the barcode web-search
use — a stored value wins over the add-on config; blank falls back to it."""
from ..extensions import db
from ..models import AppSetting

AI_KEYS = ("ollama_url", "ollama_model", "ollama_search_key")


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
