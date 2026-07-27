"""Instance-global AI-provider config (app_settings overrides) + its guards.

The provider config drives chat + tooling and is edited only by the founding
household's owner (instance admin). No live vendor calls here.
"""


def _second_group_owner_token(client):
    """A second self-registered user owns a NEW group (not the founding one)."""
    client.post("/api/v1/users/register",
                json={"email": "b@b.com", "password": "password", "name": "B"})
    return client.post("/api/v1/users/login",
                       json={"username": "b@b.com", "password": "password"}).get_json()["token"]


def test_ai_settings_roundtrip_and_effective(auth_client, app):
    r = auth_client.put("/api/v1/settings/ai", json={
        "provider": "ollama", "baseUrl": "http://ollama.local:11434",
        "model": "qwen2.5", "apiKey": "sk-ollama", "ollamaSearchKey": "sk-search",
    }).get_json()
    assert r["provider"] == "ollama" and r["model"] == "qwen2.5"
    assert r["baseUrl"] == "http://ollama.local:11434"
    assert r["apiKeySet"] is True and r["hasSearchKey"] is True

    g = auth_client.get("/api/v1/settings/ai").get_json()
    assert g["provider"] == "ollama" and g["model"] == "qwen2.5"
    assert set(g["validProviders"]) == {"ollama", "openai", "claude"}

    with app.app_context():
        from app.services.ai.provider_config import effective
        from app.services.ai.registry import get_provider
        eff = effective()
        assert eff.OLLAMA_HOST == "http://ollama.local:11434"
        assert eff.OLLAMA_SEARCH_KEY == "sk-search"
        assert get_provider().name == "ollama"


def test_ai_settings_get_never_leaks_secrets(auth_client):
    auth_client.put("/api/v1/settings/ai", json={
        "provider": "openai", "apiKey": "sk-secret", "model": "gpt-4o-mini"})
    body = auth_client.get("/api/v1/settings/ai").get_json()
    assert "sk-secret" not in str(body)
    assert body["apiKeySet"] is True  # presence signalled, value withheld


def test_ai_settings_blank_api_key_not_clobbered(auth_client):
    auth_client.put("/api/v1/settings/ai", json={"provider": "openai", "apiKey": "sk-1"})
    auth_client.put("/api/v1/settings/ai", json={"provider": "openai", "model": "m2"})  # no key
    assert auth_client.get("/api/v1/settings/ai").get_json()["apiKeySet"] is True


def test_ai_settings_rejects_ssrf_base_url(auth_client):
    r = auth_client.put("/api/v1/settings/ai", json={
        "provider": "openai", "baseUrl": "http://169.254.169.254/v1"})
    assert r.status_code == 422


def test_ai_settings_rejects_unknown_provider(auth_client):
    assert auth_client.put("/api/v1/settings/ai",
                           json={"provider": "gpt5-hype"}).status_code == 422


def test_ai_settings_disable_overrides_env_provider(auth_client, app):
    app.config["AI_PROVIDER"] = "ollama"  # add-on/env sets a provider
    auth_client.put("/api/v1/settings/ai", json={"provider": ""})  # admin disables in UI
    assert auth_client.get("/api/v1/settings/ai").get_json()["provider"] == ""
    with app.app_context():
        from app.services.ai.provider_config import effective
        assert effective().AI_PROVIDER == ""  # explicit off beats the env provider


def test_ai_settings_clear_api_key(auth_client):
    auth_client.put("/api/v1/settings/ai", json={"provider": "openai", "apiKey": "sk-1"})
    assert auth_client.get("/api/v1/settings/ai").get_json()["apiKeySet"] is True
    auth_client.put("/api/v1/settings/ai", json={"provider": "openai", "clearApiKey": True})
    assert auth_client.get("/api/v1/settings/ai").get_json()["apiKeySet"] is False


def test_ai_settings_switch_provider_preserves_and_does_not_pollute(auth_client):
    # Save Ollama with a URL/model, switch to OpenAI (URL omitted, as the UI does on
    # switch), then switch back to Ollama with nothing else — its saved values survive
    # and never leaked into the OpenAI namespace.
    auth_client.put("/api/v1/settings/ai", json={
        "provider": "ollama", "baseUrl": "http://ollama.local:11434", "model": "m1"})
    auth_client.put("/api/v1/settings/ai", json={"provider": "openai", "model": "gpt-4o-mini"})
    openai_view = auth_client.get("/api/v1/settings/ai").get_json()
    assert openai_view["baseUrl"] != "http://ollama.local:11434"  # no cross-pollution
    auth_client.put("/api/v1/settings/ai", json={"provider": "ollama"})  # switch back only
    back = auth_client.get("/api/v1/settings/ai").get_json()
    assert back["baseUrl"] == "http://ollama.local:11434" and back["model"] == "m1"


def test_ai_settings_put_rejects_non_founding_owner_403(auth_client):
    token = _second_group_owner_token(auth_client)
    auth_client.environ_base["HTTP_AUTHORIZATION"] = token
    r = auth_client.put("/api/v1/settings/ai", json={"provider": "ollama"})
    assert r.status_code == 403


def test_ai_settings_get_hidden_from_non_founding_owner_403(auth_client):
    token = _second_group_owner_token(auth_client)
    auth_client.environ_base["HTTP_AUTHORIZATION"] = token
    assert auth_client.get("/api/v1/settings/ai").status_code == 403
