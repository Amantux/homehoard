"""Config has one source: the settings registry resolved by load_settings()."""
import ast
import inspect
from pathlib import Path

import pytest

import app.config as config_module
from app import create_app
from app.config import Config
from app.settings import FIELDS_BY_NAME, load_settings
from app.services.ai import provider_config

APP_DIR = Path(__file__).resolve().parent.parent / "app"
MODEL_FIELDS = ("CLAUDE_MODEL", "OPENAI_MODEL", "OLLAMA_MODEL")


def test_config_module_reads_no_environment():
    tree = ast.parse(inspect.getsource(config_module))
    env_reads = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and n.attr in ("environ", "getenv")]
    assert env_reads == []


def test_config_declares_no_field_values():
    """An inherited class attribute would become an explicit override for every
    Config subclass — the import-time second source this shim removed."""
    assert not [n for n in FIELDS_BY_NAME if hasattr(Config, n)]


@pytest.mark.parametrize("raw", ["1", "true", "yes"])
def test_env_override_reaches_app_config(tmp_path, monkeypatch, raw):
    monkeypatch.setenv("HBOX_DISABLE_AUTH", raw)
    monkeypatch.setenv("HBOX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HBOX_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("HBOX_SECRET_KEY", "x" * 40)
    monkeypatch.setenv("HBOX_WORKER_ENABLED", "0")

    class Sub(Config):
        PROXY_HOPS = 0

    app = create_app(Sub)
    expected = load_settings(ha_options={}, validate=False).values
    assert app.config["DISABLE_AUTH"] is True
    for name in ("DISABLE_AUTH", "ALLOW_REGISTRATION", "AI_PROVIDER",
                 "CLAUDE_MODEL", "MIN_PASSWORD_LENGTH"):
        assert app.config[name] == expected[name], name


def test_model_defaults_have_one_source():
    for name in MODEL_FIELDS:
        default = FIELDS_BY_NAME[name].default
        hits = [p for p in APP_DIR.rglob("*.py")
                if f'"{default}"' in p.read_text(encoding="utf-8")]
        assert [p.name for p in hits] == ["settings.py"], (name, hits)
        # ...and provider_config falls back to exactly that default.
        assert getattr(provider_config.effective_settings({}, {}), name) == default
