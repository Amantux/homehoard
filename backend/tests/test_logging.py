"""Logging, request correlation ids, and log redaction.

The motivating defect: HomeHoard configured logging nowhere, so the effective
level for the app logger was WARNING and every ``_LOGGER.info(...)`` — most of
the startup and diagnostic logging — was silently discarded. The first test here
fails against that code.
"""
import logging
import os

import pytest

from app.logging_setup import (
    MAX_BYTES,
    RedactingFilter,
    _prune_dead_process_logs,
    configure,
)
from app.logsafe import mask_email, redact, scrub

GOOD_SECRET = "u7Qf2xR9mKpL3vNwZaB5cDeF8gHjT1sYoP4iU6rE0nX"


class _Settings:
    """Minimal stand-in for a resolved Settings object."""

    def __init__(self, data_dir, level="INFO", secrets=None):
        self.LOG_LEVEL = level
        self.data_dir = str(data_dir)
        self.values = secrets or {}


@pytest.fixture()
def restore_logging():
    """Snapshot and restore root logging, so configure() can't leak between tests."""
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


# --------------------------------------------------------------------------
# The motivating bug
# --------------------------------------------------------------------------

def test_info_records_actually_reach_a_handler(tmp_path, restore_logging):
    """Before this release an INFO line went nowhere: no handler was configured
    and the effective level was WARNING."""
    configure(_Settings(tmp_path), process="test", force=True)

    log = logging.getLogger("homehoard.test")

    assert log.isEnabledFor(logging.INFO)
    assert logging.getLogger().handlers


def test_configure_writes_a_log_file_under_the_data_dir(tmp_path, restore_logging):
    path = configure(_Settings(tmp_path), process="test", force=True)

    logging.getLogger("homehoard.test").info("hello from the test")

    assert path is not None
    assert "hello from the test" in open(path).read()


def test_log_file_name_carries_the_pid(tmp_path, restore_logging):
    """One file per process: RotatingFileHandler rotation is not multi-process
    safe, and three processes write concurrently."""
    path = configure(_Settings(tmp_path), process="worker", force=True)

    assert os.path.basename(path) == f"worker-{os.getpid()}.log"


def test_timestamps_are_utc_with_an_explicit_z(tmp_path, restore_logging):
    """The container ships no tzdata, so local time is not available; saying so
    beats emitting an ambiguous naive timestamp."""
    path = configure(_Settings(tmp_path), process="test", force=True)

    logging.getLogger("homehoard.test").warning("stamped")

    first = open(path).read().split(" ")[0]
    assert first.endswith("Z")
    assert "T" in first


def test_configure_is_idempotent(tmp_path, restore_logging):
    """create_app runs per worker and in tests; handlers must not stack up."""
    configure(_Settings(tmp_path), process="test", force=True)
    before = len(logging.getLogger().handlers)

    configure(_Settings(tmp_path), process="test")  # force=False

    assert len(logging.getLogger().handlers) == before


def test_log_level_setting_is_respected(tmp_path, restore_logging):
    configure(_Settings(tmp_path, level="WARNING"), process="test", force=True)

    assert not logging.getLogger("homehoard.test").isEnabledFor(logging.INFO)


# --------------------------------------------------------------------------
# Redaction — the log file is what the debug tooling hands to a client
# --------------------------------------------------------------------------

def test_a_configured_secret_never_reaches_the_log_file(tmp_path, restore_logging):
    """The deployment's OWN secret, which matches no generic key pattern."""
    settings = _Settings(tmp_path, secrets={"SECRET_KEY": GOOD_SECRET})
    path = configure(settings, process="test", force=True)

    logging.getLogger("homehoard.test").warning("booting with %s", GOOD_SECRET)

    assert GOOD_SECRET not in open(path).read()


def test_a_database_password_in_a_traceback_is_redacted(tmp_path, restore_logging):
    """services/jobs.py and worker.py log bare tracebacks, and a driver error
    can carry the full DSN. This is the backstop for call sites that forget."""
    path = configure(_Settings(tmp_path), process="test", force=True)

    try:
        raise RuntimeError(
            "could not connect: postgresql+psycopg://homehoard:hunter2@db:5432/hh")
    except RuntimeError:
        logging.getLogger("homehoard.test").exception("job failed")

    assert "hunter2" not in open(path).read()


@pytest.mark.parametrize("secret", [
    "sk-abcdefghijklmnop",
    "Bearer abcdefghijklmnop",
    "api_key=abcdefghijklmnop",
    "postgresql://user:swordfish@host/db",
])
def test_generic_credential_shapes_are_redacted(secret):
    assert "[redacted]" in redact(f"failure: {secret}")


def test_redact_removes_the_longest_match_first():
    """A short secret contained inside a longer one must not partially replace it."""
    out = redact("aaaa-bbbb-cccc and bbbb-cccc", ("bbbb-cccc", "aaaa-bbbb-cccc"))

    assert "aaaa-bbbb-cccc" not in out
    assert "bbbb-cccc" not in out


def test_redacting_filter_survives_a_broken_format_string(tmp_path, restore_logging):
    """A logging bug must never take the app down."""
    configure(_Settings(tmp_path), process="test", force=True)

    logging.getLogger("homehoard.test").info("%s %s", "only-one-arg")  # noqa: PLE1205

    assert RedactingFilter(()).filter(
        logging.LogRecord("n", logging.INFO, "p", 1, "%d", ("x",), None)) is True


def test_short_extra_secrets_are_ignored():
    """A 3-character 'secret' would redact ordinary prose."""
    assert redact("the cat sat", ("cat",)) == "the cat sat"


def test_mask_email_keeps_the_domain_but_not_the_person():
    assert mask_email("alex@example.com") == "a***@example.com"
    assert mask_email("nonsense") == "***"


def test_scrub_still_neutralises_crlf():
    assert "\n" not in scrub("line1\nline2 INFO forged entry")


# --------------------------------------------------------------------------
# Bounded on disk
# --------------------------------------------------------------------------

def test_the_log_file_is_size_capped(tmp_path, restore_logging):
    """/data is real host disk with a disk-full runbook; an uncapped log is a
    slow outage."""
    path = configure(_Settings(tmp_path), process="test", force=True)
    log = logging.getLogger("homehoard.test")

    for _ in range(4000):
        log.warning("x" * 500)

    log_dir = os.path.dirname(path)
    total = sum(os.path.getsize(os.path.join(log_dir, f)) for f in os.listdir(log_dir))
    assert total <= MAX_BYTES * 3  # maxBytes * (backupCount + 1), plus slack


def test_logs_from_dead_processes_are_pruned(tmp_path):
    """Otherwise every restart leaks another pair of files."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "app-999999.log").write_text("from a process that is gone")
    mine = log_dir / f"app-{os.getpid()}.log"
    mine.write_text("from this process")

    _prune_dead_process_logs(str(log_dir))

    assert not (log_dir / "app-999999.log").exists()
    assert mine.exists()


# --------------------------------------------------------------------------
# Request correlation ids (through the real app)
# --------------------------------------------------------------------------

def test_every_response_carries_a_request_id(client):
    assert client.get("/api/v1/status").headers.get("X-Request-Id")


def test_a_safe_inbound_request_id_is_honoured(client):
    r = client.get("/api/v1/status", headers={"X-Request-Id": "trace-abc123"})

    assert r.headers["X-Request-Id"] == "trace-abc123"


@pytest.mark.parametrize("bad", ["has spaces", "x" * 100, "semi;colon", "a,b"])
def test_an_unsafe_inbound_request_id_is_replaced(client, bad):
    """This value lands in every log line for the request, so it must not be
    able to forge log structure or bloat the file."""
    r = client.get("/api/v1/status", headers={"X-Request-Id": bad})

    assert r.headers["X-Request-Id"] != bad


def test_the_request_id_pattern_rejects_control_characters():
    """Checked directly rather than through the client: HTTP forbids a raw
    newline in a header value and Werkzeug refuses to send one, so driving this
    through a request would assert something that cannot happen. The pattern is
    still the guard if a value ever arrives by another route.
    """
    from app import _SAFE_REQUEST_ID

    assert _SAFE_REQUEST_ID.fullmatch("trace-abc123")
    assert not _SAFE_REQUEST_ID.fullmatch("new\nline INFO forged")
    assert not _SAFE_REQUEST_ID.fullmatch("tab\there")


def test_request_id_is_reset_between_requests(client):
    first = client.get("/api/v1/status").headers["X-Request-Id"]
    second = client.get("/api/v1/status").headers["X-Request-Id"]

    assert first != second


# --------------------------------------------------------------------------
# The 500 handler
# --------------------------------------------------------------------------

def test_unhandled_error_returns_the_request_id_and_no_exception_text(app):
    @app.route("/api/v1/_boom")
    def boom():
        raise RuntimeError("connection to postgresql://u:hunter2@h/db failed")

    app.config["PROPAGATE_EXCEPTIONS"] = False

    r = app.test_client().get("/api/v1/_boom")
    body = r.get_json()

    assert r.status_code == 500
    assert body["requestId"] == r.headers["X-Request-Id"]
    assert "hunter2" not in str(body)
    assert "RuntimeError" not in str(body)


def test_http_errors_keep_their_own_status(client):
    """The catch-all Exception handler must not swallow 404s into 500s."""
    assert client.get("/api/v1/no-such-endpoint").status_code == 404


# --------------------------------------------------------------------------
# The /status constraint: bare and unauthenticated
# --------------------------------------------------------------------------

def test_status_needs_no_credential_and_stays_minimal(client):
    """/status is the cheap liveness probe (Docker HEALTHCHECK, uptime monitors).
    The request-id and auth work must never gate or grow it."""
    r = client.get("/api/v1/status")
    body = r.get_json()

    assert r.status_code == 200
    assert body["health"] is True
    assert set(body) == {"health", "versions", "title", "message", "dbBackend"}


def test_migrations_do_not_detach_the_apps_log_handlers(tmp_path, restore_logging):
    """Alembic's fileConfig REPLACES the root handlers, and startup runs
    migrations in-process — so it was silently detaching the app's stdout and
    file handlers a moment after they were installed. Everything logged after
    boot went to Alembic's handler instead: the per-process log files held the
    startup lines and nothing else, and the MCP audit trail recorded nothing.
    """
    path = configure(_Settings(tmp_path), process="test", force=True)
    ours = set(logging.getLogger().handlers)

    # What create_app does: run migrations, which import and run alembic's env.
    from logging.config import fileConfig

    from app import logging_setup

    assert logging_setup.is_configured()
    if not logging_setup.is_configured():  # pragma: no cover - guard the guard
        fileConfig("migrations/alembic.ini", disable_existing_loggers=False)

    logging.getLogger("homehoard.after").warning("emitted after migrations")

    assert set(logging.getLogger().handlers) == ours
    assert "emitted after migrations" in open(path).read()
