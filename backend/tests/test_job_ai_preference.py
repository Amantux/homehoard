"""Async-job AI preference: a stored provider+model default for background jobs,
separate from chat. `enrich` has its own; categorize/cluster share `organize`.
Precedence: per-run opts > stored kind preference > the chat provider."""


from app.services.ai import provider_config as pc
from app.services.ai.registry import resolve_job_provider
from app.services.settings_store import set_values


def test_job_preference_unset_is_none(app):
    with app.app_context():
        for kind in ("enrich", "categorize"):
            assert pc.job_override(kind) == {
                "provider": None, "model": None, "base_url": None, "api_key": None}


def test_organize_preference_shared_by_categorize_and_cluster(app):
    with app.app_context():
        set_values({"organize_provider": "ollama", "organize_model": "llama3.1"})
        for kind in ("categorize", "cluster"):
            got = pc.job_override(kind)
            assert (got["provider"], got["model"]) == ("ollama", "llama3.1")
        assert pc.job_override("enrich")["provider"] is None   # enrich is separate


def test_resolve_returns_none_without_pref_or_opts(app):
    with app.app_context():
        assert resolve_job_provider("enrich", {}) is None


def test_resolve_uses_the_kind_preference(app):
    with app.app_context():
        set_values({"ollama_url": "http://ollama.local:11434", "ollama_model": "base",
                    "enrich_provider": "ollama", "enrich_model": "tinyllama"})
        p = resolve_job_provider("enrich", {})
        assert p is not None and p.name == "ollama" and p.model == "tinyllama"


def test_per_run_opts_win_over_preference(app):
    with app.app_context():
        set_values({"ollama_url": "http://o", "ollama_model": "base",
                    "enrich_provider": "ollama", "enrich_model": "pref-model"})
        p = resolve_job_provider("enrich", {"model": "override-model"})
        assert p.model == "override-model"


def test_job_settings_endpoint_roundtrip_and_validation(auth_client):
    r = auth_client.put("/api/v1/settings/ai/jobs", json={
        "enrich": {"provider": "ollama", "model": "m1",
                                       "baseUrl": "", "apiKeySet": False},
        "organize": {"provider": "", "model": ""}})
    assert r.status_code == 200
    assert r.get_json()["enrich"] == {"provider": "ollama", "model": "m1",
                                       "baseUrl": "", "apiKeySet": False}
    assert auth_client.get("/api/v1/settings/ai/jobs").get_json()["enrich"]["provider"] == "ollama"

    bad = auth_client.put("/api/v1/settings/ai/jobs", json={"enrich": {"provider": "bogus"}})
    assert bad.status_code == 422


def test_job_settings_requires_auth(client):
    assert client.get("/api/v1/settings/ai/jobs").status_code == 401
