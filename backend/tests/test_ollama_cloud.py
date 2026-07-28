"""Ollama Cloud as a distinct provider: pinned to ollama.com, key-required, and
its key is namespaced separately from a local Ollama's."""
import pytest

from app.services.ai import provider_config as pc
from app.services.ai.base import ProviderError
from app.services.ai.registry import get_provider
from app.services.settings_store import set_values


def test_ollama_cloud_is_a_valid_provider():
    assert "ollama_cloud" in pc.VALID_PROVIDERS


def test_ollama_cloud_listed_in_settings_view(app):
    with app.app_context():
        assert "ollama_cloud" in pc.settings_view()["validProviders"]


def test_ollama_cloud_requires_a_key(app):
    with app.app_context():
        set_values({"ai_provider": "ollama_cloud", "ollama_cloud_model": "gpt-oss:20b"})
        with pytest.raises(ProviderError):
            get_provider()  # model set but no key → not fully configured
        set_values({"ollama_cloud_api_key": "sk-cloud-abc"})
        p = get_provider()
        assert p.name == "ollama_cloud"
        assert p.host == "https://ollama.com"  # host is pinned, not user-editable
        assert p.model == "gpt-oss:20b"
        assert p.api_key == "sk-cloud-abc"


def test_ollama_cloud_key_is_separate_from_local_ollama(app):
    with app.app_context():
        # A local-Ollama key must NOT satisfy Ollama Cloud — separate namespace.
        set_values({"ai_provider": "ollama_cloud", "ollama_cloud_model": "m",
                    "ollama_api_key": "local-only-key"})
        with pytest.raises(ProviderError):
            get_provider()
