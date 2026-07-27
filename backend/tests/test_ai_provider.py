"""Provider-config resolution, registry selection, and the SSRF URL guard.

Pure-unit where possible (config passed as a plain dict; overrides injected), so no
DB/app context and no live vendor calls.
"""
import pytest

from app.services.ai import provider_config as pc
from app.services.ai.base import ProviderError, extract_json
from app.services.ai.url_guard import llm_url_ok

_BASE = {
    "AI_PROVIDER": "", "OLLAMA_URL": "http://localhost:11434", "OLLAMA_MODEL": "llama3.1",
    "OPENAI_MODEL": "gpt-4o-mini", "CLAUDE_MODEL": "claude-opus-4-8", "AI_TIMEOUT_SECONDS": 60,
}


def test_override_wins_over_env_default():
    eff = pc.effective_settings(_BASE, {"ai_provider": "ollama", "ollama_model": "qwen2.5"})
    assert eff.AI_PROVIDER == "ollama" and eff.OLLAMA_MODEL == "qwen2.5"
    assert eff.OLLAMA_HOST == "http://localhost:11434"  # falls back to env default


def test_blank_override_falls_back_to_env():
    eff = pc.effective_settings({**_BASE, "OLLAMA_MODEL": "envmodel"}, {"ollama_model": ""})
    assert eff.OLLAMA_MODEL == "envmodel"


def test_namespaced_keys_do_not_cross_providers():
    eff = pc.effective_settings(_BASE, {"ai_provider": "openai", "openai_api_key": "sk-oa",
                                        "claude_api_key": "sk-cl"})
    # OpenAI is active; its key resolves, Claude's stays isolated on its own attr.
    assert eff.OPENAI_API_KEY == "sk-oa" and eff.ANTHROPIC_API_KEY == "sk-cl"


@pytest.mark.parametrize("url,ok", [
    ("", True),
    ("http://localhost:11434", True),
    ("http://192.168.1.50:11434", True),
    ("http://169.254.169.254/latest/meta-data", False),  # cloud metadata (link-local)
    ("ftp://example.com", False),
    ("http://[::ffff:169.254.169.254]/v1", False),        # IPv4-mapped metadata
])
def test_ssrf_guard(url, ok):
    assert llm_url_ok(url)[0] is ok


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```')["a"] == 1
    assert extract_json('here you go: {"b": 2} thanks')["b"] == 2
    with pytest.raises(ProviderError):
        extract_json("[1, 2, 3]")  # a bare array is not a JSON object


def test_get_provider_raises_when_unset(app):
    from app.services.ai.registry import get_provider, get_provider_or_none
    with app.app_context():
        with pytest.raises(ProviderError):
            get_provider()
        assert get_provider_or_none() is None
