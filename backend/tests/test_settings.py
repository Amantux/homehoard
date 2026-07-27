"""UI-editable AI provider config (app_settings overrides), used by enrich."""


def test_ai_settings_override_flows_into_enrich(auth_client, app):
    r = auth_client.put("/api/v1/settings/ai", json={
        "ollamaUrl": "http://ollama.local:11434", "ollamaModel": "qwen2.5",
        "ollamaSearchKey": "sk-test",
    }).get_json()
    assert r["model"] == "qwen2.5" and r["hasSearchKey"] is True

    g = auth_client.get("/api/v1/settings/ai").get_json()
    assert g["url"] == "http://ollama.local:11434"
    assert g["overridden"]["ollama_model"] is True

    with app.app_context():
        from app.services import enrich
        cfg = enrich._cfg()
        assert cfg["url"] == "http://ollama.local:11434"
        assert cfg["model"] == "qwen2.5" and cfg["key"] == "sk-test"


def test_ai_settings_blank_key_is_not_clobbered(auth_client):
    auth_client.put("/api/v1/settings/ai", json={"ollamaSearchKey": "sk-1"})
    auth_client.put("/api/v1/settings/ai", json={"ollamaModel": "m2"})  # no key sent
    assert auth_client.get("/api/v1/settings/ai").get_json()["hasSearchKey"] is True


def _second_group_owner_token(client):
    """A second self-registered user owns a NEW group (not the founding one)."""
    client.post("/api/v1/users/register",
                json={"email": "b@b.com", "password": "password", "name": "B"})
    return client.post("/api/v1/users/login",
                       json={"username": "b@b.com", "password": "password"}).get_json()["token"]


def test_ai_settings_put_rejects_non_founding_owner_403(auth_client):
    # auth_client is the founding owner; a second household's owner must not repoint shared AI infra.
    token = _second_group_owner_token(auth_client)
    auth_client.environ_base["HTTP_AUTHORIZATION"] = token

    r = auth_client.put("/api/v1/settings/ai", json={"ollamaUrl": "http://evil.example"})

    assert r.status_code == 403


def test_ai_settings_get_hidden_from_non_founding_owner_403(auth_client):
    token = _second_group_owner_token(auth_client)
    auth_client.environ_base["HTTP_AUTHORIZATION"] = token

    assert auth_client.get("/api/v1/settings/ai").status_code == 403
