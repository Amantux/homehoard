"""The single configuration contract for HomeHoard.

Every setting the application understands is declared exactly once, in
``FIELDS`` below. Nothing else in the codebase may read ``os.environ`` for a
``HBOX_`` value — the inventory, the docs, the ``config_check`` CLI and the CI
documentation test all derive from this one table, so they cannot drift apart
the way scattered ``os.environ.get`` calls did.

This replaces two overlapping mechanisms:

* ``docker-entrypoint.sh`` used to run **eleven** separate ``python3 -c``
  invocations, each re-reading ``/data/options.json`` and re-declaring its own
  default. The shell and the app were therefore two copies of the same
  configuration, and they had already diverged: the shell defaulted
  ``disable_auth`` to **True**, while ``Config`` defaulted it to **False**.
* ``app/config.py`` read ``os.environ`` at *import* time, so a value was
  captured once per process forever, an unrecognised boolean silently became
  ``False``, and a malformed integer was an unhandled traceback at import.

Precedence (highest wins)
-------------------------
1. **Explicit overrides** passed to ``load_settings(overrides=...)`` — used by
   ``create_app(SomeConfig)`` and by tests, which must be able to build several
   differently-configured apps in one process.
2. **Home Assistant add-on options** (``/data/options.json``), when present.
3. **Environment variables**.
4. **Declared defaults** in ``FIELDS``.

Why HA options outrank the environment — this is the one non-obvious choice.
Inside the add-on, options.json is the *only* surface an operator can edit; the
environment is baked into the image and Supervisor. If the environment won,
toggling "disable_auth" in the HA UI would silently do nothing, which is a
worse failure than the reverse. Outside HA the file does not exist, so the
environment is authoritative there. This makes the old entrypoint's behaviour
(it overwrote the env from options.json unconditionally) explicit and testable
rather than accidental.

Resolution is a pure function of its inputs: no import-time capture, no
``os.environ`` reads at class-definition time, and no directory creation as a
side effect of importing a module.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import stat
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

PLACEHOLDER_SECRETS = frozenset({
    "change-me-in-production", "change-me", "changeme", "secret", "password",
    "test", "dev", "development", "please-change-me",
})

# Substrings that mark a value as an example rather than a real secret. Exact
# matching is not enough: the shipped compose file said
# "please-change-me-to-a-long-random-string", which is long enough to pass a
# length check and would otherwise have been accepted as a production secret.
PLACEHOLDER_MARKERS = ("change-me", "changeme", "change_me", "example",
                       "placeholder", "your-secret", "yoursecret", "insecure",
                       "replace-me", "notasecret", "not-a-secret")

MIN_SECRET_LENGTH = 32

REDACTED = "***redacted***"


# scheme://user:pass@host — the credentials, not the whole URL.
_URL_USERINFO = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)[^/@\s]*:[^/@\s]*@")


def strip_url_credentials(value: str) -> str:
    """Replace embedded userinfo in a URL with a redaction marker.

    A provider base URL is not declared secret — knowing you point at
    ``http://ollama.lan:11434`` is exactly what makes the startup log useful.
    But operators do embed credentials in those URLs, and add-on logs get pasted
    into public GitHub issues. Redact the credentials, keep the host.
    """
    return _URL_USERINFO.sub(lambda m: f"{m.group('scheme')}{REDACTED}@", value)


def _is_placeholder(value: str) -> bool:
    v = value.strip().lower()
    return v in PLACEHOLDER_SECRETS or any(m in v for m in PLACEHOLDER_MARKERS)


class ConfigError(RuntimeError):
    """Raised when configuration is invalid. Carries every problem at once.

    Reporting one error per run turns fixing a misconfigured deployment into a
    guessing game, so validation collects all of them before raising.

    Subclasses RuntimeError deliberately: bad configuration is a startup
    failure, and create_app already refused to boot with ``RuntimeError`` for
    exactly these cases. Callers (and tests) that catch RuntimeError keep
    working whether the refusal comes from here or from create_app.
    """

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Invalid configuration:\n" + "\n".join(f"  - {e}" for e in errors))


# --------------------------------------------------------------------------
# Parsers. Each raises ValueError with a message naming the accepted values —
# silently coercing an unknown value to a default is how a production system
# ends up with registration open because someone wrote "HBOX_ALLOW_REGISTRATION=maybe".
# --------------------------------------------------------------------------

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def parse_bool(raw: str) -> bool:
    v = str(raw).strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise ValueError(
        f"expected a boolean, got {raw!r}. Accepted: "
        f"{', '.join(sorted(_TRUE))} (true) / {', '.join(sorted(_FALSE))} (false)"
    )


def int_between(low: int, high: int) -> Callable[[str], int]:
    def parse(raw: str) -> int:
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ValueError(f"expected an integer, got {raw!r}")
        if not (low <= value <= high):
            raise ValueError(f"expected an integer between {low} and {high}, got {value}")
        return value
    return parse


def float_between(low: float, high: float) -> Callable[[str], float]:
    def parse_float(raw: str) -> float:
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            raise ValueError(f"expected a number, got {raw!r}")
        if not (low <= value <= high):
            raise ValueError(f"expected a number between {low} and {high}, got {value}")
        return value
    return parse_float


def one_of(*allowed: str) -> Callable[[str], str]:
    def parse(raw: str) -> str:
        v = str(raw).strip()
        if v not in allowed:
            shown = ", ".join(repr(a) if a else "'' (disabled)" for a in allowed)
            raise ValueError(f"expected one of {shown}, got {v!r}")
        return v
    return parse


def provider_choice(*allowed: str) -> Callable[[str], str]:
    """Like :func:`one_of`, but case- and whitespace-insensitive.

    Deliberately more lenient than ``one_of``: the previous code lowercased the
    provider name at the point of use (``registry._configured_name``), so
    ``HBOX_AI_PROVIDER=Ollama`` works today. A strict parser would turn a
    working deployment into a container that refuses to boot on upgrade, which
    is not an acceptable trade for tidiness. Garbage is still rejected.
    """
    def parse(raw: str) -> str:
        v = str(raw).strip().lower()
        if v not in allowed:
            shown = ", ".join(repr(a) if a else "'' (disabled)" for a in allowed)
            raise ValueError(f"expected one of {shown}, got {raw!r}")
        return v
    return parse


def csv_list(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in str(raw).split(",") if p.strip())


def normalize_db_scheme(url: str) -> str:
    """Rewrite ``postgres://`` and bare ``postgresql://`` to ``postgresql+psycopg://``.

    Pure rewriting, no validation, and an unrecognised scheme passes through
    untouched. ``services/db_copy`` needs exactly this: it must inspect the
    normalized URL and raise its own curated ``DbCopyError`` for a non-Postgres
    target, rather than have a raw ValueError cross the API boundary.
    :func:`normalize_db_url` layers validation on top for everyone else.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def normalize_db_url(url: str) -> str:
    """Validate a database URL's scheme+driver and normalize it.

    HomeHoard supports exactly two backends: SQLite and PostgreSQL via psycopg
    (v3, the installed driver). A bare ``postgresql://`` defaults to psycopg2
    (NOT installed) and would crash with a cryptic ImportError at first query,
    so we normalize it to ``postgresql+psycopg://``. ``postgres://`` (Heroku
    style) is accepted and normalized too. Any other scheme or Postgres driver
    raises ValueError. Applied at the point of use, so it guards the env
    DATABASE_URL and the shared-Postgres DSN alike.
    """
    url = normalize_db_scheme(url)
    scheme = url.split("://", 1)[0].lower()
    base, _, driver = scheme.partition("+")
    if base == "sqlite":
        return url
    if base == "postgresql":
        if not driver:
            return "postgresql+psycopg" + url[len("postgresql"):]
        if driver != "psycopg":
            raise ValueError(
                f"unsupported Postgres driver '+{driver}'. HomeHoard ships psycopg "
                "(v3); use postgresql+psycopg://…"
            )
        return url
    raise ValueError(
        f"unsupported database scheme {scheme!r}. Only sqlite:// and "
        "postgresql+psycopg:// are supported."
    )


def as_str(raw: str) -> str:
    return str(raw)


_UNSET = object()


@dataclass(frozen=True)
class Field:
    name: str                      # without the HBOX_ prefix
    parse: Callable[[str], Any]
    default: Any
    doc: str
    secret: bool = False
    ha_option: str | None = None   # matching key in options.json
    # Default applied when running INSIDE Home Assistant and the option key is
    # absent from options.json. Some settings are correctly permissive
    # standalone and correctly restrictive as an add-on; the deleted shell block
    # encoded exactly that, and dropping it silently flipped a default open.
    ha_default: Any = _UNSET
    restart_required: bool = True
    supports_file: bool = False    # honours HBOX_<NAME>_FILE (Docker secrets)

    @property
    def env_var(self) -> str:
        return f"HBOX_{self.name}"


# --------------------------------------------------------------------------
# THE INVENTORY. Adding a setting anywhere else is a bug that CI will catch.
#
# This covers every value the Flask app reads AND every value the standalone
# scripts read (mcp_server.py, ha_discovery.py, run.py). Those run as separate
# processes that never import Config, which is exactly why they used to drift —
# mcp_server.py had its own boolean parser for MCP_EXPOSE_EXTERNAL.
# --------------------------------------------------------------------------
FIELDS: tuple[Field, ...] = (
    # --- storage ---
    Field("DATA_DIR", as_str, "./data",
          "Directory for the SQLite database, attachments and persisted secrets."),
    Field("DATABASE_URL", as_str, "",
          "Full SQLAlchemy URL. Blank = SQLite inside DATA_DIR. Postgres is "
          "supported: postgresql+psycopg://user:pass@host:5432/dbname.",
          secret=True, ha_option="database_url", supports_file=True),
    Field("MIGRATE_FROM_SQLITE", parse_bool, False,
          "One-shot: when DATABASE_URL points at an EMPTY Postgres and a local "
          "SQLite database exists, copy the SQLite data across at startup "
          "before serving.",
          ha_option="migrate_from_sqlite"),
    Field("USE_SHARED_POSTGRES", parse_bool, False,
          "Home Assistant only: discover the Shared PostgreSQL add-on and use a "
          "database it provisions for HomeHoard. Ignored when DATABASE_URL is set.",
          ha_option="use_shared_postgres"),
    Field("POSTGRES_PROVISION_TOKEN", as_str, "",
          "Token for the Shared PostgreSQL add-on's provisioning API. Leave blank "
          "to auto-obtain it via discovery; set it to the add-on's token if "
          "discovery can't supply it.",
          secret=True, ha_option="postgres_provision_token"),

    # --- security ---
    Field("SECRET_KEY", as_str, "",
          "JWT signing key. Blank = generated once and persisted in DATA_DIR. "
          "Deliberately has no add-on option: it must never be minted per boot, "
          "which would log every user out and void every API token.",
          secret=True, supports_file=True),
    Field("JWT_HOURS", int_between(1, 24 * 365), 72,
          "How long an issued token stays valid, in hours."),
    Field("DISABLE_AUTH", parse_bool, False,
          "Bind every request to a single local user. ONLY safe behind an "
          "authenticating proxy such as Home Assistant ingress.",
          ha_option="disable_auth"),
    Field("ALLOW_REGISTRATION", parse_bool, True,
          "Allow anyone who can reach the app to create an account.",
          # True standalone: /users/register has no first-user exception, so a
          # fresh install with auth on could never create its first account.
          # False as an add-on, matching config.yaml and the deleted shell line
          # (`.get('allow_registration', False)`) — without this, an options.json
          # missing the key silently opened registration on upgrade.
          ha_option="allow_registration", ha_default=False),
    Field("MIN_PASSWORD_LENGTH", int_between(1, 128), 8,
          "Minimum password length enforced on register / change-password."),
    Field("WORKER_ENABLED", parse_bool, True,
          "Run the in-process background-job worker thread (async AI tooling)."),

    # --- network / proxy ---
    Field("PORT", int_between(1, 65535), 7745, "HTTP port for the app."),
    Field("CORS_ORIGINS", csv_list, (),
          "Comma-separated origins allowed to make credentialed cross-origin "
          "requests. Empty = same-origin only (correct for normal deployments)."),
    Field("PROXY_HOPS", int_between(0, 10), 0,
          "How many reverse proxies sit in front. 0 = do not trust "
          "X-Forwarded-* headers at all."),
    Field("RATELIMIT_ENABLED", parse_bool, True,
          "Enable request rate limiting (disabled automatically under tests)."),

    # --- AI provider (chat + tooling) ---
    Field("AI_PROVIDER", provider_choice("", "claude", "ollama", "ollama_cloud", "openai"), "",
          "Which AI backend to use. Blank disables AI features cleanly. Can also "
          "be set in the UI, which wins over this value."),
    Field("AI_TIMEOUT_SECONDS", int_between(1, 600), 60,
          "Per-request timeout for AI provider calls."),
    Field("AI_CONFIDENCE_THRESHOLD", float_between(0.0, 1.0), 0.8,
          "Auto-categorization: a proposed label at/above this model-reported "
          "confidence (and matching an existing label) is applied automatically; "
          "below it, or a new label, goes to the review queue."),
    Field("ANTHROPIC_API_KEY", as_str, "", "API key for the claude provider.",
          secret=True, supports_file=True),
    Field("CLAUDE_MODEL", as_str, "claude-opus-4-8", "Model for the claude provider."),
    Field("OPENAI_API_KEY", as_str, "", "API key for the openai provider.",
          secret=True, supports_file=True),
    Field("OPENAI_MODEL", as_str, "gpt-4o-mini", "Model for the openai provider."),
    Field("OPENAI_BASE_URL", as_str, "",
          "Override the OpenAI API base URL (for compatible gateways / local SLM "
          "servers such as LM Studio, vLLM, llama.cpp)."),
    Field("OLLAMA_URL", as_str, "http://localhost:11434",
          "Base URL of the Ollama server."),
    Field("OLLAMA_MODEL", as_str, "llama3.1", "Model for the ollama provider."),
    Field("OLLAMA_SEARCH_KEY", as_str, "",
          "Ollama API key (ollama.com) for the hosted web search, used to enrich "
          "items with a short searchable description. Blank = enrichment is off.",
          secret=True, supports_file=True, ha_option="ollama_search_key"),
    Field("OLLAMA_CLOUD_API_KEY", as_str, "",
          "API key for Ollama Cloud (ollama.com), a distinct provider from a "
          "local Ollama server.", secret=True, supports_file=True),
    Field("OLLAMA_CLOUD_MODEL", as_str, "", "Model for the ollama_cloud provider."),

    # --- barcode identification ---
    Field("BARCODE_LOOKUP", parse_bool, False,
          "Identify a product from a scanned UPC/EAN. Off by default because it "
          "makes outbound network calls.",
          ha_option="barcode_lookup"),
    Field("BARCODE_DB_URL", as_str, "https://api.upcitemdb.com/prod/trial/lookup",
          "Product barcode database endpoint."),
    Field("BARCODE_DB_KEY", as_str, "",
          "API key for the barcode database. Blank uses the keyless trial tier.",
          secret=True, supports_file=True, ha_option="barcode_db_key"),

    # --- MCP (Home Assistant Assist) ---
    Field("MCP_ENABLED", parse_bool, True,
          "Run the MCP server so Home Assistant Assist can use HomeHoard as a tool.",
          ha_option="enable_mcp"),
    Field("MCP_HOST", as_str, "0.0.0.0", "Bind address for the MCP server."),
    Field("MCP_PORT", int_between(1, 65535), 7766, "Port for the MCP server (SSE)."),
    Field("MCP_API", as_str, "",
          "Backend API URL the MCP server calls. Blank = derived from PORT."),
    Field("MCP_API_TOKEN", as_str, "",
          "Token the MCP server uses when app auth is enabled.",
          secret=True, supports_file=True),
    Field("MCP_SERVER_TOKEN", as_str, "",
          "Bearer token Home Assistant must present to reach the MCP server. "
          "Blank leaves it unauthenticated (only safe on a trusted network).",
          secret=True, supports_file=True),
    Field("MCP_EXPOSE_EXTERNAL", parse_bool, False,
          "Reach the MCP server from OUTSIDE Home Assistant. When on, every "
          "request must present a Full- or MCP-scoped API key, and the server "
          "refuses to start until such a key exists — so it is never open. You "
          "must also map the MCP port in the add-on's Network tab.",
          ha_option="mcp_expose_external"),

    # --- misc ---
    Field("MAX_UPLOAD_MB", int_between(1, 1024), 50, "Maximum upload size in MB."),
    Field("FRONTEND_DIST", as_str, "",
          "Path to the built SPA. Blank = the location baked into the image."),
    Field("DISCOVERY_HOST", as_str, "",
          "Override the hostname advertised to Home Assistant via Supervisor "
          "discovery. Blank = ask the Supervisor for the add-on's own hostname."),
    Field("DEBUG", parse_bool, False,
          "Flask debug mode. NEVER enable in production — it exposes an "
          "interactive debugger that executes arbitrary code."),
)

FIELDS_BY_NAME = {f.name: f for f in FIELDS}


@dataclass(frozen=True)
class Settings:
    """Resolved, validated configuration. Immutable after startup."""

    values: dict[str, Any]
    warnings: tuple[str, ...] = ()
    sources: dict[str, str] = field(default_factory=dict)

    def __getattr__(self, item: str) -> Any:
        try:
            return object.__getattribute__(self, "values")[item]
        except KeyError:
            raise AttributeError(item)

    def __getitem__(self, item: str) -> Any:
        return self.values[item]

    # -- derived -----------------------------------------------------------
    @property
    def data_dir(self) -> str:
        return os.path.abspath(self.values["DATA_DIR"])

    @property
    def attachments_dir(self) -> str:
        return os.path.join(self.data_dir, "attachments")

    @property
    def jwt_expires(self) -> timedelta:
        return timedelta(hours=self.values["JWT_HOURS"])

    @property
    def max_upload_bytes(self) -> int:
        return self.values["MAX_UPLOAD_MB"] * 1024 * 1024

    @property
    def sqlalchemy_uri(self) -> str:
        # Explicit URL always wins. Stripped first: a whitespace-only value is
        # "unset", not a URL whose scheme happens to be blank.
        explicit = (self.values["DATABASE_URL"] or "").strip()
        if explicit:
            # Wrapped: an unusable database URL is a configuration failure, and
            # ConfigError is a RuntimeError, so callers see one refusal type
            # whether it came from validation or from here (this path is also
            # reached with validate=False). normalize_db_url names only the
            # scheme/driver, never the URL, so no credential is echoed.
            try:
                return normalize_db_url(explicit)
            except ValueError as exc:
                raise ConfigError([f"HBOX_DATABASE_URL: {exc}"]) from None
        # Shared PostgreSQL: the entrypoint's provisioning step (pg_provision)
        # writes the discovered DSN here; read it rather than routing a runtime
        # value through the env/options precedence chain.
        if self.values["USE_SHARED_POSTGRES"]:
            try:
                with open(os.path.join(self.data_dir, ".database_url")) as fh:
                    url = fh.read().strip()
                if url:
                    # Same wrapping as the explicit URL above: a provisioned DSN
                    # we cannot load is a configuration failure, not a stray
                    # ValueError from a helper. The message names only the
                    # scheme/driver, never the DSN, which embeds a password.
                    try:
                        return normalize_db_url(url)
                    except ValueError as exc:
                        raise ConfigError(
                            [f"the provisioned database DSN: {exc}"]) from None
            except OSError:
                # The provisioned-DSN file is optional: absent/unreadable simply
                # means "not provisioned yet", so fall through to the SQLite
                # default rather than failing startup.
                pass
        return f"sqlite:///{os.path.join(self.data_dir, 'homehoard.db')}"

    @property
    def mcp_api(self) -> str:
        return self.values["MCP_API"] or f"http://127.0.0.1:{self.values['PORT']}/api/v1"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.values["AI_PROVIDER"])

    def redacted(self) -> dict[str, Any]:
        """Effective settings with every secret replaced. Safe to print/log."""
        out: dict[str, Any] = {}
        for f in FIELDS:
            value = self.values[f.name]
            if f.secret and value:
                value = REDACTED
            elif isinstance(value, tuple):
                value = list(value)
            elif isinstance(value, str) and value:
                # Applies to EVERY string field, not a hand-listed set of URL
                # fields: a list would go stale the moment someone adds one.
                value = strip_url_credentials(value)
            out[f.name] = value
        return out


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------

def load_ha_options(path: str = "/data/options.json") -> dict[str, Any]:
    """Read Home Assistant add-on options. Parsed ONCE, here, and nowhere else.

    A malformed file is reported rather than swallowed: an add-on that silently
    ignores its own options is indistinguishable from one that is broken.
    """
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError([f"{path} could not be read as JSON: {exc}"])
    if not isinstance(data, dict):
        raise ConfigError([f"{path} must contain a JSON object, got {type(data).__name__}"])
    return data


def _read_secret_file(path: str, name: str, errors: list[str]) -> str | None:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError as exc:
        errors.append(f"{name}: cannot read secret file {path!r}: {exc}")
        return None


def load_settings(
    env: dict[str, str] | None = None,
    overrides: dict[str, Any] | None = None,
    ha_options: dict[str, Any] | None = None,
    ha_options_path: str = "/data/options.json",
    validate: bool = True,
) -> Settings:
    """Resolve settings from all sources. Pure: no I/O beyond reading inputs.

    Raises ConfigError listing EVERY problem found, so a misconfigured deploy
    is fixed in one pass rather than one error at a time.
    """
    env = os.environ if env is None else env
    overrides = overrides or {}
    if ha_options is None:
        ha_options = load_ha_options(ha_options_path)
    in_ha = bool(ha_options)

    errors: list[str] = []
    warnings: list[str] = []
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}

    for f in FIELDS:
        raw: Any = None
        source = "default"

        # 4. defaults  <  3. environment  <  2. HA options  <  1. overrides
        if f.supports_file and env.get(f.env_var + "_FILE"):
            content = _read_secret_file(env[f.env_var + "_FILE"], f.env_var, errors)
            if content is not None:
                raw, source = content, "file"
        if raw is None and f.env_var in env and env[f.env_var] != "":
            raw, source = env[f.env_var], "env"
        if f.ha_option and f.ha_option in ha_options:
            ha_raw = ha_options[f.ha_option]
            # An empty string in options.json means "not set" (the HA UI writes
            # "" for a cleared optional field), so it must not beat a default.
            if ha_raw != "" or f.default == "":
                raw, source = ha_raw, "ha_option"
        elif in_ha and f.ha_default is not _UNSET:
            raw, source = f.ha_default, "ha_default"
        if f.name in overrides:
            raw, source = overrides[f.name], "override"

        if raw is None:
            values[f.name] = f.default
            sources[f.name] = "default"
            continue

        # Overrides may pass already-typed values (a test passing DEBUG=True).
        if source == "override" and not isinstance(raw, str):
            values[f.name] = raw
            sources[f.name] = source
            continue
        if source == "ha_default":
            values[f.name] = raw
            sources[f.name] = source
            continue
        # options.json is typed JSON: a real bool stays a bool.
        if source == "ha_option" and isinstance(raw, bool) and f.parse is parse_bool:
            values[f.name] = raw
            sources[f.name] = source
            continue

        try:
            values[f.name] = f.parse(raw)
            sources[f.name] = source
        except ValueError as exc:
            shown = REDACTED if f.secret else repr(raw)
            errors.append(f"{f.env_var} (from {source}, value {shown}): {exc}")
            values[f.name] = f.default
            sources[f.name] = "default"

    if errors:
        raise ConfigError(errors)

    # validate=False resolves values without the cross-field rules. Used by
    # Config.sqlalchemy_uri(), which answers "which database?" for the bare
    # `alembic` CLI — a recovery path that must not abort because CORS_ORIGINS
    # or SECRET_KEY is unrelatedly wrong.
    if validate:
        _validate_semantics(values, sources, in_ha, errors, warnings)
        if errors:
            raise ConfigError(errors)

    return Settings(values=values, warnings=tuple(warnings), sources=sources)


def _validate_semantics(values, sources, in_ha, errors, warnings) -> None:
    """Cross-field rules. This is where unsafe COMBINATIONS are caught.

    Individually valid settings can combine into an unambiguously unsafe
    deployment; those fail closed. Suspicious-but-legitimate ones warn.
    """
    # --- the signing secret ---
    secret = values["SECRET_KEY"]
    # Only when authentication is on. With DISABLE_AUTH the key signs nothing an
    # attacker can use, and refusing to boot would break the documented
    # behind-ingress deployment (see test_default_secret_allowed_when_auth_disabled).
    #
    # There is deliberately NO "relaxed inside Home Assistant" case: create_app
    # enforces the same length unconditionally when auth is on, so relaxing it
    # here made config_check pass a configuration the app then refused to start
    # on — the gate reporting "valid" and the container dying seconds later is
    # the exact failure the gate exists to prevent. A BLANK secret is generated
    # and persisted, and short-circuits before either check.
    if secret and not values["DISABLE_AUTH"]:
        if _is_placeholder(secret):
            errors.append(
                "HBOX_SECRET_KEY is a known placeholder value. Generate one with: "
                "python3 -c 'import secrets;print(secrets.token_urlsafe(32))'"
            )
        elif len(secret) < MIN_SECRET_LENGTH:
            errors.append(
                f"HBOX_SECRET_KEY is only {len(secret)} characters; at least "
                f"{MIN_SECRET_LENGTH} are required when authentication is enabled."
            )

    # --- auth mode ---
    if values["DISABLE_AUTH"]:
        if values["ALLOW_REGISTRATION"]:
            warnings.append(
                "DISABLE_AUTH is on, so ALLOW_REGISTRATION has no effect "
                "(every request is already the same local user)."
            )
        if not in_ha and values["PROXY_HOPS"] == 0:
            warnings.append(
                "DISABLE_AUTH is on outside Home Assistant with PROXY_HOPS=0. "
                "Every request will be treated as an authenticated local user. This "
                "is only safe if something in front of HomeHoard authenticates "
                "callers — set HBOX_PROXY_HOPS to confirm a proxy is present."
            )
        if values["CORS_ORIGINS"]:
            errors.append(
                "DISABLE_AUTH=true together with HBOX_CORS_ORIGINS is unsafe: it lets "
                "another website drive this API as the local user. Remove CORS_ORIGINS "
                "or enable authentication."
            )

    # --- debug ---
    if values["DEBUG"]:
        if in_ha:
            errors.append("HBOX_DEBUG cannot be enabled in the Home Assistant add-on.")
        else:
            warnings.append(
                "HBOX_DEBUG is on. The Werkzeug debugger executes arbitrary code — "
                "never expose this to an untrusted network."
            )

    # --- CORS ---
    if "*" in values["CORS_ORIGINS"]:
        errors.append(
            "HBOX_CORS_ORIGINS may not contain '*': credentialed requests from any "
            "origin would be permitted. List explicit origins instead."
        )
    for origin in values["CORS_ORIGINS"]:
        if not re.match(r"^https?://", origin):
            errors.append(
                f"HBOX_CORS_ORIGINS entry {origin!r} must start with http:// or https://")

    # --- AI provider coherence. Warnings only: AI is optional, and a missing
    # key must never stop the inventory app from serving. ---
    provider = values["AI_PROVIDER"]
    _key_for = {
        "claude": ("ANTHROPIC_API_KEY", "HBOX_ANTHROPIC_API_KEY"),
        "openai": ("OPENAI_API_KEY", "HBOX_OPENAI_API_KEY"),
        "ollama_cloud": ("OLLAMA_CLOUD_API_KEY", "HBOX_OLLAMA_CLOUD_API_KEY"),
    }
    if provider in _key_for:
        name, env_var = _key_for[provider]
        if not values[name]:
            warnings.append(
                f"AI_PROVIDER={provider} but {env_var} is not set. AI features will "
                "report as unavailable until a key is configured (env or the "
                "Settings UI); the rest of the app is unaffected."
            )

    # A base URL that isn't a URL is a warning, not a fatal: AI is optional, and
    # taking the whole inventory app down for it would be a worse outcome.
    for name, env_var in (("OLLAMA_URL", "HBOX_OLLAMA_URL"),
                          ("OPENAI_BASE_URL", "HBOX_OPENAI_BASE_URL")):
        value = values[name]
        if value and not re.match(r"^https?://", value):
            warnings.append(
                f"{env_var}={value!r} does not start with http:// or https://; "
                "that provider will fail to connect."
            )

    # --- database ---
    uri = (values["DATABASE_URL"] or "").strip()
    if uri:
        try:
            normalize_db_url(uri)
        except ValueError as exc:
            errors.append(f"HBOX_DATABASE_URL: {exc}")
    if values["MIGRATE_FROM_SQLITE"] and not uri and not values["USE_SHARED_POSTGRES"]:
        warnings.append(
            "MIGRATE_FROM_SQLITE is on but no Postgres target is configured "
            "(HBOX_DATABASE_URL is blank and USE_SHARED_POSTGRES is off), so there "
            "is nothing to migrate to and the setting is inert."
        )

    # --- MCP ---
    if values["MCP_ENABLED"] and values["MCP_PORT"] == values["PORT"]:
        errors.append(
            f"HBOX_MCP_PORT and HBOX_PORT are both {values['PORT']}; "
            "the MCP server and the web app cannot share a port."
        )
    if values["MCP_EXPOSE_EXTERNAL"] and not values["MCP_ENABLED"]:
        warnings.append(
            "MCP_EXPOSE_EXTERNAL is on but MCP_ENABLED is off, so no MCP server "
            "runs and the setting is inert."
        )


# --------------------------------------------------------------------------
# Secret persistence
# --------------------------------------------------------------------------

def ensure_secret_key(supplied: str, data_dir: str) -> tuple[str, bool]:
    """Return (secret, was_generated), persisting a generated one.

    A signing key regenerated on every restart logs every user out and voids
    every issued API token — including MCP keys — which looks like data loss
    rather than a config problem. The entrypoint used to default HBOX_SECRET_KEY
    to `head -c 32 /dev/urandom`, so that happened on EVERY container start. If
    the operator does not supply one we generate it ONCE and persist it beside
    the database, so restarts are non-events.

    A supplied value is returned untouched — including a known placeholder, so
    the caller's fail-closed check still sees (and rejects) it.
    """
    if supplied:
        return supplied, False

    path = os.path.join(data_dir, ".secret_key")
    try:
        with open(path) as fh:
            existing = fh.read().strip()
    except OSError:
        existing = ""
    if existing:
        return existing, False

    generated = secrets.token_urlsafe(48)
    os.makedirs(data_dir, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(generated)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600 — owner only
    return generated, True
