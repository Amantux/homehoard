"""Background jobs can run on their own SLM server.

Mirrors myMeal. The point: a fast hosted model for interactive chat, and a small
local model on your own box for the slow async work. That needs a per-area BASE
URL, not just a provider — two Ollama servers are the common case and both would
otherwise resolve the single shared ollama_url.
"""
import pytest

from app.services.ai import provider_config as pc
from app.services.ai.registry import provider_for, resolve_job_provider
from app.services.settings_store import set_values


def test_an_unset_area_still_means_same_as_chat(app):
    """The default must not change now that the override carries a URL and key."""
    with app.app_context():
        assert resolve_job_provider("enrich") is None
        assert pc.job_override("enrich") == {
            "provider": None, "model": None, "base_url": None, "api_key": None}


def test_a_job_can_point_at_its_own_server(app):
    with app.app_context():
        set_values({"enrich_provider": "ollama", "enrich_model": "qwen3:4b",
                    "enrich_base_url": "http://192.168.1.50:11434"})
        p = resolve_job_provider("enrich")
        assert p.host == "http://192.168.1.50:11434"
        assert p.model == "qwen3:4b"


def test_the_async_server_does_not_leak_into_chat(app):
    """If the async host bled into the chat provider it would silently move
    interactive traffic onto the slow box."""
    with app.app_context():
        set_values({"ai_provider": "ollama", "ollama_url": "http://fast-box:11434",
                    "enrich_provider": "ollama",
                    "enrich_base_url": "http://slow-box:11434"})
        assert provider_for().host == "http://fast-box:11434"
        assert resolve_job_provider("enrich").host == "http://slow-box:11434"


def test_the_two_job_areas_are_independent(app):
    with app.app_context():
        set_values({"enrich_provider": "ollama", "enrich_base_url": "http://box-a:11434",
                    "organize_provider": "ollama", "organize_base_url": "http://box-b:11434"})
        assert resolve_job_provider("enrich").host == "http://box-a:11434"
        assert resolve_job_provider("categorize").host == "http://box-b:11434"


def test_a_per_run_option_beats_the_stored_server(app):
    with app.app_context():
        set_values({"enrich_provider": "ollama", "enrich_base_url": "http://stored:11434"})
        p = resolve_job_provider("enrich", opts={"baseUrl": "http://per-run:11434"})
        assert p.host == "http://per-run:11434"


# --- the allowlist ----------------------------------------------------------

def test_the_new_keys_are_registered_in_the_settings_allowlist(app):
    """set_values() silently drops anything not in AI_KEYS, so a key that is
    missing from it looks saved and simply is not."""
    from app.services.settings_store import AI_KEYS

    for area in ("enrich", "organize"):
        for field in ("base_url", "api_key"):
            assert f"{area}_{field}" in AI_KEYS


# --- secrets ----------------------------------------------------------------

def test_the_async_api_key_is_never_returned(auth_client):
    auth_client.put("/api/v1/settings/ai/jobs",
                    json={"enrich": {"provider": "ollama", "apiKey": "sk-async-secret"}})

    body = auth_client.get("/api/v1/settings/ai/jobs").get_json()

    assert body["enrich"]["apiKeySet"] is True
    assert "sk-async-secret" not in str(body)
    assert "apiKey" not in body["enrich"]


def test_a_blank_apikey_on_resave_keeps_the_stored_one(auth_client, app):
    """Sends apiKey="" explicitly, which is what a form does when the field is
    left empty. An earlier version of this test simply omitted the field, so
    "blank means clear" was never actually exercised — the mutation survived.
    """
    auth_client.put("/api/v1/settings/ai/jobs", json={"enrich": {"apiKey": "sk-keep-me"}})
    auth_client.put("/api/v1/settings/ai/jobs",
                    json={"enrich": {"model": "other", "apiKey": ""}})

    with app.app_context():
        assert pc.job_override("enrich")["api_key"] == "sk-keep-me"


def test_clearing_the_async_key_is_explicit(auth_client, app):
    auth_client.put("/api/v1/settings/ai/jobs", json={"enrich": {"apiKey": "sk-gone"}})
    auth_client.put("/api/v1/settings/ai/jobs", json={"enrich": {"clearApiKey": True}})

    with app.app_context():
        assert pc.job_override("enrich")["api_key"] is None


# --- the URL guard ----------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "http://169.254.169.254",          # cloud metadata
    "file:///etc/passwd",
    "not-a-url",
])
def test_an_unsafe_async_server_is_refused_on_save(auth_client, bad):
    r = auth_client.put("/api/v1/settings/ai/jobs", json={"enrich": {"baseUrl": bad}})
    assert r.status_code == 422


def test_an_unsafe_server_supplied_per_run_is_refused_at_use(app):
    """Per-run opts never pass the settings guard, so the check has to exist at
    the point of USE too."""
    from app.services.ai.base import ProviderError

    with app.app_context():
        with pytest.raises(ProviderError) as ei:
            resolve_job_provider("enrich", opts={"provider": "ollama",
                                                 "baseUrl": "http://169.254.169.254"})
    assert "not allowed" in str(ei.value)


def test_a_private_lan_server_is_allowed(auth_client):
    """Self-hosting on the LAN is the entire use case — it must not be blocked."""
    r = auth_client.put("/api/v1/settings/ai/jobs",
                        json={"enrich": {"provider": "ollama",
                                         "baseUrl": "http://192.168.1.50:11434"}})
    assert r.status_code == 200
    assert r.get_json()["enrich"]["baseUrl"] == "http://192.168.1.50:11434"
