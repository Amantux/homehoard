"""Tests for the configuration contract (app/settings.py).

Covers the three things scattered ``os.environ.get`` calls could not do: reject
a bad value instead of silently coercing it, report where a value came from, and
resolve several different configurations in one process.

Not to be confused with ``test_settings.py``, which covers the DB-backed
AI-provider override store (``services/settings_store.py``) — a different layer.
"""
import json
import os
import subprocess
import sys
import textwrap

import pytest

from app.settings import (
    FIELDS,
    FIELDS_BY_NAME,
    MIN_SECRET_LENGTH,
    REDACTED,
    ConfigError,
    Settings,
    as_str,
    csv_list,
    ensure_secret_key,
    int_between,
    load_ha_options,
    load_settings,
    normalize_db_url,
    parse_bool,
    provider_choice,
)

# A secret that passes both the placeholder and the length checks.
GOOD_SECRET = "u7Qf2xR9mKpL3vNwZaB5cDeF8gHjT1sYoP4iU6rE0nX"


CONFIG_YAML = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "homehoard", "config.yaml"))


def _shipped_addon_options():
    """Keys under `options:` in the add-on manifest.

    Hand-parsed rather than via PyYAML: yaml is not in backend/requirements.txt,
    so importing it would pass locally and fail in CI. The block is a flat
    mapping of scalars, which this handles exactly.
    """
    keys, inside = [], False
    with open(CONFIG_YAML) as fh:
        for line in fh:
            if line.startswith("options:"):
                inside = True
                continue
            if inside:
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                if not line.startswith((" ", "\t")):
                    break  # next top-level key ends the block
                keys.append(line.strip().split(":", 1)[0].strip())
    return keys


def resolve(**kw):
    """load_settings with the process environment and options.json excluded, so
    a test never depends on where it is run."""
    kw.setdefault("env", {})
    kw.setdefault("ha_options", {})
    return load_settings(**kw)


# --------------------------------------------------------------------------
# Parsers — the whole point is that a bad value is REJECTED, not coerced
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["1", "true", "TRUE", " yes ", "on"])
def test_parse_bool_true_forms_return_true(raw):
    assert parse_bool(raw) is True


@pytest.mark.parametrize("raw", ["0", "false", "FALSE", " no ", "off"])
def test_parse_bool_false_forms_return_false(raw):
    assert parse_bool(raw) is False


def test_parse_bool_unknown_value_raises_rather_than_defaulting_false():
    """The old Config._bool() returned False for anything unrecognised, so
    HBOX_ALLOW_REGISTRATION=maybe quietly turned registration off."""
    with pytest.raises(ValueError) as exc:
        parse_bool("maybe")

    assert "maybe" in str(exc.value)
    assert "true" in str(exc.value)  # names the accepted values


def test_load_settings_invalid_bool_names_the_variable_and_accepted_values():
    with pytest.raises(ConfigError) as exc:
        resolve(env={"HBOX_ALLOW_REGISTRATION": "maybe"})

    (msg,) = exc.value.errors
    assert "HBOX_ALLOW_REGISTRATION" in msg
    assert "'maybe'" in msg


def test_int_between_out_of_range_raises():
    with pytest.raises(ValueError):
        int_between(1, 10)("11")


def test_load_settings_non_integer_port_is_rejected():
    with pytest.raises(ConfigError) as exc:
        resolve(env={"HBOX_PORT": "not-a-port"})

    assert "HBOX_PORT" in exc.value.errors[0]


def test_load_settings_reports_every_error_at_once():
    """One error per run turns fixing a deployment into a guessing game."""
    with pytest.raises(ConfigError) as exc:
        resolve(env={
            "HBOX_PORT": "banana",
            "HBOX_DISABLE_AUTH": "perhaps",
            "HBOX_AI_CONFIDENCE_THRESHOLD": "9",
        })

    assert len(exc.value.errors) == 3


def test_load_settings_unknown_ai_provider_is_rejected():
    with pytest.raises(ConfigError):
        resolve(env={"HBOX_AI_PROVIDER": "gpt5-turbo-max"})


def test_load_settings_ai_provider_is_case_insensitive():
    """registry._configured_name() lowercases, so HBOX_AI_PROVIDER=Ollama works
    today. A strict parser would refuse to boot a working deployment."""
    assert resolve(env={"HBOX_AI_PROVIDER": "Ollama"}).AI_PROVIDER == "ollama"
    assert provider_choice("", "ollama")(" OLLAMA ") == "ollama"


def test_load_settings_blank_ai_provider_disables_ai():
    s = resolve(env={"HBOX_AI_PROVIDER": ""})

    assert s.AI_PROVIDER == ""
    assert s.ai_enabled is False


def test_csv_list_trims_and_drops_empty_entries():
    assert csv_list("a, b ,,c") == ("a", "b", "c")


@pytest.mark.parametrize("url,expected", [
    ("sqlite:///x.db", "sqlite:///x.db"),
    ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
])
def test_normalize_db_url_pins_the_installed_driver(url, expected):
    assert normalize_db_url(url) == expected


@pytest.mark.parametrize("url", ["mysql://u:p@h/db", "postgresql+psycopg2://u:p@h/db"])
def test_normalize_db_url_unsupported_scheme_or_driver_raises(url):
    with pytest.raises(ValueError):
        normalize_db_url(url)


def test_load_settings_bad_database_url_refuses_to_start():
    with pytest.raises(ConfigError) as exc:
        resolve(env={"HBOX_DATABASE_URL": "mysql://u:p@h/db"})

    assert "HBOX_DATABASE_URL" in exc.value.errors[0]


def test_load_settings_database_url_password_is_not_echoed_in_the_error():
    """DATABASE_URL is secret=True; psycopg-style DSN leaks are how two of these
    apps previously published a Postgres password."""
    with pytest.raises(ConfigError) as exc:
        resolve(env={"HBOX_DATABASE_URL": "mysql://user:hunter2@h/db"})

    assert "hunter2" not in "\n".join(exc.value.errors)


# --------------------------------------------------------------------------
# Precedence
# --------------------------------------------------------------------------

def test_load_settings_with_nothing_set_uses_the_declared_default():
    s = resolve()

    assert s.PORT == 7745
    assert s.sources["PORT"] == "default"


def test_load_settings_env_beats_default():
    s = resolve(env={"HBOX_PORT": "9000"})

    assert s.PORT == 9000
    assert s.sources["PORT"] == "env"


def test_load_settings_ha_option_beats_env():
    """options.json is the only surface an operator can edit inside the add-on,
    so a toggle in the HA UI must not be silently overridden by the image's env."""
    s = resolve(env={"HBOX_DISABLE_AUTH": "false"}, ha_options={"disable_auth": True})

    assert s.DISABLE_AUTH is True
    assert s.sources["DISABLE_AUTH"] == "ha_option"


def test_load_settings_override_beats_everything():
    s = resolve(env={"HBOX_PORT": "9000"}, overrides={"PORT": 1234})

    assert s.PORT == 1234
    assert s.sources["PORT"] == "override"


def test_load_settings_empty_env_var_does_not_beat_default():
    s = resolve(env={"HBOX_PORT": ""})

    assert s.PORT == 7745
    assert s.sources["PORT"] == "default"


def test_load_settings_empty_ha_option_does_not_clobber_a_real_default():
    """The HA UI writes "" for a cleared optional field; that means 'unset'."""
    s = resolve(ha_options={"enable_mcp": ""})

    assert s.MCP_ENABLED is True
    assert s.sources["MCP_ENABLED"] == "default"


def test_load_settings_empty_ha_option_wins_when_the_default_is_blank():
    s = resolve(env={"HBOX_BARCODE_DB_KEY": "from-env"},
                ha_options={"barcode_db_key": ""})

    assert s.BARCODE_DB_KEY == ""


def test_load_settings_ha_json_booleans_stay_booleans():
    """options.json is typed JSON — a real bool must not go through the string
    parser (Python's str(True) is 'True', which the shell used to emit)."""
    s = resolve(ha_options={"barcode_lookup": True})

    assert s.BARCODE_LOOKUP is True


def test_load_settings_unknown_ha_option_is_ignored_not_fatal():
    s = resolve(ha_options={"some_option_from_a_future_version": "x"})

    assert s.PORT == 7745


def test_load_settings_reports_the_source_of_every_value():
    s = resolve(env={"HBOX_PORT": "9000"}, ha_options={"disable_auth": True},
                overrides={"MIN_PASSWORD_LENGTH": 12})

    assert s.sources["PORT"] == "env"
    assert s.sources["DISABLE_AUTH"] == "ha_option"
    assert s.sources["MIN_PASSWORD_LENGTH"] == "override"
    assert s.sources["MCP_PORT"] == "default"


# --------------------------------------------------------------------------
# The options.json adapter — the single parse point
# --------------------------------------------------------------------------

def test_load_ha_options_missing_file_returns_empty(tmp_path):
    assert load_ha_options(str(tmp_path / "nope.json")) == {}


def test_load_ha_options_invalid_json_is_actionable(tmp_path):
    path = tmp_path / "options.json"
    path.write_text("{not json")

    with pytest.raises(ConfigError) as exc:
        load_ha_options(str(path))

    assert "could not be read as JSON" in exc.value.errors[0]


def test_load_ha_options_non_object_is_rejected(tmp_path):
    path = tmp_path / "options.json"
    path.write_text('["a", "b"]')

    with pytest.raises(ConfigError):
        load_ha_options(str(path))


def test_load_settings_resolves_every_shipped_addon_option(tmp_path):
    """Regression test for the eleven `python3 -c` calls the entrypoint used to
    run: the same file, parsed once, must produce the same settings."""
    options = {
        "disable_auth": True,
        "allow_registration": False,
        "enable_mcp": True,
        "mcp_expose_external": False,
        "ollama_search_key": "sk-search",
        "barcode_lookup": True,
        "barcode_db_key": "sk-barcode",
        "database_url": "postgresql://u:p@h/db",
        "migrate_from_sqlite": False,
        "use_shared_postgres": True,
        "postgres_provision_token": "tok",
    }
    path = tmp_path / "options.json"
    path.write_text(json.dumps(options))

    s = load_settings(env={}, ha_options=load_ha_options(str(path)))

    assert s.DISABLE_AUTH is True
    assert s.MCP_ENABLED is True
    assert s.MCP_EXPOSE_EXTERNAL is False
    assert s.OLLAMA_SEARCH_KEY == "sk-search"
    assert s.BARCODE_LOOKUP is True
    assert s.BARCODE_DB_KEY == "sk-barcode"
    assert s.DATABASE_URL == "postgresql://u:p@h/db"
    assert s.MIGRATE_FROM_SQLITE is False
    assert s.USE_SHARED_POSTGRES is True
    assert s.POSTGRES_PROVISION_TOKEN == "tok"


def test_load_settings_disable_auth_defaults_closed_when_the_option_is_absent():
    """DELIBERATE behaviour change, documented in the commit message.

    The old shell read `.get('disable_auth', True)` while Config defaulted to
    False — two different answers to the same question. We keep Config's False:
    an options.json that somehow lacks the key must not silently disable
    authentication. The shipped config.yaml always sets the key, so a normal
    add-on install is unaffected.
    """
    s = resolve(ha_options={"enable_mcp": True})

    assert s.DISABLE_AUTH is False


def test_allow_registration_defaults_closed_as_an_addon_open_standalone():
    """The deleted shell read `.get('allow_registration', False)`; the Field
    default is True. Without an HA-specific default, an options.json missing the
    key silently OPENED registration on upgrade — the mirror of the disable_auth
    case, failing the other way.

    It cannot simply default False everywhere: /users/register has no first-user
    exception, so a standalone install with auth on could never be bootstrapped.
    """
    standalone = resolve()
    addon = resolve(ha_options={"disable_auth": True, "enable_mcp": True})

    assert standalone.ALLOW_REGISTRATION is True
    assert addon.ALLOW_REGISTRATION is False
    assert addon.sources["ALLOW_REGISTRATION"] == "ha_default"


def test_an_explicit_addon_option_still_beats_the_ha_default():
    s = resolve(ha_options={"allow_registration": True, "disable_auth": True})

    assert s.ALLOW_REGISTRATION is True
    assert s.sources["ALLOW_REGISTRATION"] == "ha_option"


def test_validate_false_skips_cross_field_rules_only():
    """The bare `alembic` CLI asks for the database URL; that must not abort
    because CORS_ORIGINS is unrelatedly wrong."""
    env = {"HBOX_CORS_ORIGINS": "example.com", "HBOX_DATABASE_URL": "sqlite:///x.db"}

    with pytest.raises(ConfigError):
        load_settings(env=env, ha_options={})

    assert load_settings(env=env, ha_options={}, validate=False).sqlalchemy_uri == "sqlite:///x.db"


def test_every_shipped_addon_option_maps_to_a_declared_field():
    """Every key in the add-on's config.yaml must be read by some Field.

    Read from config.yaml rather than a list copied into this test: a
    hand-maintained copy mirrors whatever the author forgot. The first draft of
    this test omitted `allow_registration` in BOTH places and passed while the
    option was silently unwired.
    """
    shipped = set(_shipped_addon_options())

    declared = {f.ha_option for f in FIELDS if f.ha_option}

    assert shipped, "could not read options from config.yaml"
    assert shipped <= declared, f"unwired add-on options: {sorted(shipped - declared)}"


def test_no_field_claims_an_addon_option_that_does_not_exist():
    """The other direction: a Field pointing at a key config.yaml never sets is
    dead configuration the operator has no way to reach."""
    shipped = set(_shipped_addon_options())

    declared = {f.ha_option for f in FIELDS if f.ha_option}

    assert declared <= shipped, f"options missing from config.yaml: {sorted(declared - shipped)}"


# --------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------

def test_load_settings_placeholder_secret_is_refused():
    with pytest.raises(ConfigError) as exc:
        resolve(env={"HBOX_SECRET_KEY": "change-me-in-production"})

    assert "placeholder" in exc.value.errors[0]


def test_load_settings_long_placeholder_secret_is_still_refused():
    """Long enough to pass the length check, still a placeholder."""
    with pytest.raises(ConfigError):
        resolve(env={"HBOX_SECRET_KEY": "please-change-me-to-a-long-random-string"})


@pytest.mark.parametrize("value", [
    "Change-Me-Now-0123456789012345678901",
    "my-INSECURE-key-0123456789012345678901",
    "PLACEHOLDER-0123456789012345678901234",
])
def test_load_settings_placeholder_markers_are_matched_case_insensitively(value):
    with pytest.raises(ConfigError):
        resolve(env={"HBOX_SECRET_KEY": value})


def test_load_settings_short_secret_is_refused_when_auth_is_enabled():
    with pytest.raises(ConfigError) as exc:
        resolve(env={"HBOX_SECRET_KEY": "abc123"})

    assert str(MIN_SECRET_LENGTH) in exc.value.errors[0]


def test_load_settings_accepts_a_real_random_secret():
    assert resolve(env={"HBOX_SECRET_KEY": GOOD_SECRET}).SECRET_KEY == GOOD_SECRET


def test_load_settings_with_auth_off_ignores_a_short_secret():
    """With DISABLE_AUTH the key signs nothing an attacker can use."""
    s = resolve(env={"HBOX_SECRET_KEY": "short"}, ha_options={"disable_auth": True})

    assert s.SECRET_KEY == "short"


def test_load_settings_short_secret_is_refused_inside_ha_too_when_auth_is_on():
    """There is no 'relaxed inside Home Assistant' case.

    create_app enforces the same 32-char minimum unconditionally when auth is
    on, so relaxing it here made config_check report a configuration VALID that
    the app then refused to start on seconds later — the gate saying "fine"
    while the container dies is the exact failure the gate exists to prevent.
    """
    with pytest.raises(ConfigError):
        resolve(env={"HBOX_SECRET_KEY": "short"},
                ha_options={"disable_auth": False, "enable_mcp": True})


def test_a_blank_secret_is_never_a_config_error():
    """Blank means 'generate and persist one', which is the normal add-on path."""
    assert resolve(ha_options={"disable_auth": False}).SECRET_KEY == ""


def test_secret_key_field_has_no_addon_option():
    """It must never be settable per-boot from options.json — see the field doc."""
    assert FIELDS_BY_NAME["SECRET_KEY"].ha_option is None


def test_load_settings_reads_a_secret_from_its_file_variant(tmp_path):
    path = tmp_path / "secret"
    path.write_text(GOOD_SECRET + "\n")

    s = resolve(env={"HBOX_SECRET_KEY_FILE": str(path)})

    assert s.SECRET_KEY == GOOD_SECRET
    assert s.sources["SECRET_KEY"] == "file"


def test_load_settings_unreadable_secret_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError) as exc:
        resolve(env={"HBOX_SECRET_KEY_FILE": str(tmp_path / "missing")})

    assert "secret file" in exc.value.errors[0]


def test_redacted_replaces_every_populated_secret():
    s = resolve(env={"HBOX_SECRET_KEY": GOOD_SECRET,
                     "HBOX_BARCODE_DB_KEY": "sk-very-secret"})

    out = s.redacted()

    assert out["SECRET_KEY"] == REDACTED
    assert out["BARCODE_DB_KEY"] == REDACTED
    assert GOOD_SECRET not in json.dumps(out)
    assert "sk-very-secret" not in json.dumps(out)


def test_redacted_leaves_blank_secrets_blank():
    """A blank secret shown as '***' would read as 'a key is configured'."""
    assert resolve().redacted()["OPENAI_API_KEY"] == ""


def test_every_credential_field_is_marked_secret():
    """A new key/token field that forgets secret=True would be echoed by
    config_check and by /diagnostics."""
    for f in FIELDS:
        if f.name.endswith(("_KEY", "_TOKEN")) or f.name == "DATABASE_URL":
            assert f.secret, f"{f.name} must be marked secret=True"


def test_redacted_strips_credentials_embedded_in_a_url():
    """Provider base URLs are not secret — the host is useful in the startup log
    — but operators do embed credentials in them, and add-on logs get pasted
    into public issues. The name-suffix check above cannot catch this: OLLAMA_URL
    ends in neither _KEY nor _TOKEN.
    """
    s = resolve(env={"HBOX_OLLAMA_URL": "http://user:s3cr3t@ollama.lan:11434"})

    shown = s.redacted()["OLLAMA_URL"]

    assert "s3cr3t" not in shown
    assert "ollama.lan:11434" in shown  # host kept: that is the useful part


def test_redacted_leaks_no_credential_from_any_string_field():
    """Sweeps every string field rather than a hand-listed set, so a URL setting
    added later is covered without anyone remembering to update this test."""
    env = {f.env_var: "https://user:hunter2@host.example/x"
           for f in FIELDS if f.parse is as_str}

    # validate=False: the point is redaction, not whether a URL is a legal value
    # for every field (DATABASE_URL correctly rejects a non-Postgres scheme).
    dumped = json.dumps(load_settings(env=env, ha_options={}, validate=False).redacted())

    assert "hunter2" not in dumped


def test_ensure_secret_key_persists_the_generated_key_across_restarts(tmp_path):
    first, generated = ensure_secret_key("", str(tmp_path))
    second, generated_again = ensure_secret_key("", str(tmp_path))

    assert generated is True
    assert second == first
    assert generated_again is False


def test_ensure_secret_key_writes_an_owner_only_file(tmp_path):
    ensure_secret_key("", str(tmp_path))

    assert os.stat(tmp_path / ".secret_key").st_mode & 0o077 == 0


def test_ensure_secret_key_never_overwrites_a_supplied_key(tmp_path):
    secret, generated = ensure_secret_key(GOOD_SECRET, str(tmp_path))

    assert secret == GOOD_SECRET
    assert generated is False
    assert not (tmp_path / ".secret_key").exists()


def test_ensure_secret_key_returns_a_supplied_placeholder_unchanged(tmp_path):
    """It must not 'fix' a placeholder, or the fail-closed check never sees it."""
    secret, _ = ensure_secret_key("change-me", str(tmp_path))

    assert secret == "change-me"


# --------------------------------------------------------------------------
# Unsafe combinations
# --------------------------------------------------------------------------

def test_load_settings_disable_auth_with_cors_origins_is_fatal():
    with pytest.raises(ConfigError) as exc:
        resolve(env={"HBOX_DISABLE_AUTH": "true",
                     "HBOX_CORS_ORIGINS": "https://evil.example"})

    assert "unsafe" in exc.value.errors[0]


def test_load_settings_wildcard_cors_origin_is_fatal():
    with pytest.raises(ConfigError):
        resolve(env={"HBOX_CORS_ORIGINS": "*"})


def test_load_settings_cors_origin_without_a_scheme_is_fatal():
    with pytest.raises(ConfigError):
        resolve(env={"HBOX_CORS_ORIGINS": "example.com"})


def test_load_settings_debug_inside_home_assistant_is_fatal():
    with pytest.raises(ConfigError):
        resolve(env={"HBOX_DEBUG": "true"}, ha_options={"disable_auth": True})


def test_load_settings_debug_outside_ha_only_warns():
    s = resolve(env={"HBOX_DEBUG": "true"})

    assert any("debugger" in w for w in s.warnings)


def test_load_settings_mcp_port_colliding_with_app_port_is_fatal():
    with pytest.raises(ConfigError) as exc:
        resolve(env={"HBOX_PORT": "7745", "HBOX_MCP_PORT": "7745"})

    assert "cannot share a port" in exc.value.errors[0]


def test_load_settings_mcp_port_collision_is_ignored_when_mcp_is_off():
    s = resolve(env={"HBOX_PORT": "7745", "HBOX_MCP_PORT": "7745",
                     "HBOX_MCP_ENABLED": "false"})

    assert s.MCP_ENABLED is False


def test_load_settings_disable_auth_outside_ha_without_a_proxy_warns():
    s = resolve(env={"HBOX_DISABLE_AUTH": "true"})

    assert any("PROXY_HOPS" in w for w in s.warnings)


def test_load_settings_disable_auth_behind_ha_ingress_is_warning_free():
    """The normal add-on install must produce no scary warnings."""
    s = resolve(ha_options={"disable_auth": True, "enable_mcp": True})

    assert not any("PROXY_HOPS" in w for w in s.warnings)


def test_load_settings_provider_without_its_key_warns_but_boots():
    s = resolve(env={"HBOX_AI_PROVIDER": "claude"})

    assert any("ANTHROPIC_API_KEY" in w for w in s.warnings)


def test_load_settings_ollama_url_without_a_scheme_warns_but_boots():
    """AI is optional — a bad provider URL must not take the inventory down."""
    s = resolve(env={"HBOX_OLLAMA_URL": "localhost:11434"})

    assert any("HBOX_OLLAMA_URL" in w for w in s.warnings)


def test_load_settings_migrate_from_sqlite_without_a_target_warns():
    s = resolve(env={"HBOX_MIGRATE_FROM_SQLITE": "true"})

    assert any("nothing to migrate" in w for w in s.warnings)


# --------------------------------------------------------------------------
# Derived values and purity
# --------------------------------------------------------------------------

def test_data_dir_is_always_absolute():
    assert os.path.isabs(resolve(env={"HBOX_DATA_DIR": "./rel"}).data_dir)


def test_sqlalchemy_uri_defaults_to_sqlite_inside_the_data_dir(tmp_path):
    s = resolve(env={"HBOX_DATA_DIR": str(tmp_path)})

    assert s.sqlalchemy_uri == f"sqlite:///{tmp_path / 'homehoard.db'}"


def test_sqlalchemy_uri_normalizes_an_explicit_database_url():
    s = resolve(env={"HBOX_DATABASE_URL": "postgresql://u:p@h/db"})

    assert s.sqlalchemy_uri == "postgresql+psycopg://u:p@h/db"


def test_sqlalchemy_uri_uses_the_provisioned_dsn_for_shared_postgres(tmp_path):
    (tmp_path / ".database_url").write_text("postgresql://u:p@h/db\n")

    s = resolve(env={"HBOX_DATA_DIR": str(tmp_path), "HBOX_USE_SHARED_POSTGRES": "true"})

    assert s.sqlalchemy_uri == "postgresql+psycopg://u:p@h/db"


def test_sqlalchemy_uri_falls_back_to_sqlite_when_not_yet_provisioned(tmp_path):
    """'Not provisioned yet' must never be a startup failure."""
    s = resolve(env={"HBOX_DATA_DIR": str(tmp_path), "HBOX_USE_SHARED_POSTGRES": "true"})

    assert s.sqlalchemy_uri.startswith("sqlite:///")


def test_mcp_api_is_derived_from_the_app_port_when_unset():
    assert resolve(env={"HBOX_PORT": "9000"}).mcp_api == "http://127.0.0.1:9000/api/v1"


def test_derived_scalars_match_the_old_config_computations():
    s = resolve(env={"HBOX_JWT_HOURS": "5", "HBOX_MAX_UPLOAD_MB": "3"})

    assert s.jwt_expires.total_seconds() == 5 * 3600
    assert s.max_upload_bytes == 3 * 1024 * 1024


def test_resolution_creates_no_directories(tmp_path):
    """Resolution is pure: a property must not mkdir as a side effect. The old
    Config.sqlalchemy_uri() and attachments_dir() both did."""
    target = tmp_path / "should-not-exist"

    s = resolve(env={"HBOX_DATA_DIR": str(target)})
    _ = s.data_dir, s.attachments_dir, s.sqlalchemy_uri

    assert not target.exists()


def test_importing_the_settings_module_creates_nothing(tmp_path):
    code = textwrap.dedent("""
        import os, sys
        sys.path.insert(0, os.environ["BACKEND"])
        import app.settings  # noqa: F401
        print(sorted(os.listdir(".")))
    """)
    backend = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                         env=dict(os.environ, BACKEND=backend),
                         capture_output=True, text=True, check=True)

    assert out.stdout.strip() == "[]"


def test_settings_are_immutable():
    s = resolve()

    with pytest.raises(Exception):
        s.values = {}


def test_two_apps_with_different_settings_can_coexist_in_one_process():
    """Impossible with the old import-time Config: one process, one config."""
    a = resolve(env={"HBOX_PORT": "1111"})
    b = resolve(env={"HBOX_PORT": "2222"})

    assert (a.PORT, b.PORT) == (1111, 2222)
    assert isinstance(a, Settings)


def test_unknown_setting_raises_attributeerror():
    with pytest.raises(AttributeError):
        resolve().NOT_A_SETTING
