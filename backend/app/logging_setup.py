"""Configure logging once, for every process HomeHoard runs.

Before this existed, HomeHoard configured logging **nowhere**. The effective
level for the app logger was WARNING, so every ``_LOGGER.info(...)`` — most of
the startup and diagnostic logging — was silently discarded, and the only
handler present had been installed as a side effect of Alembic's ``fileConfig``
during migrations. Logs that vanish are worse than no logs: they read as "the
app had nothing to say".

Two sinks:

* **stdout** — what the Home Assistant add-on log tab shows, and what an
  operator pastes into an issue.
* **a file** under ``<DATA_DIR>/logs/`` — because stdout is captured by the
  container runtime, not by us, so the app cannot read its own history back.
  The debug tooling reads these files.

Why one file *per process*: three processes write concurrently (two gunicorn
workers plus the MCP sidecar), and ``RotatingFileHandler`` rotation is not
multi-process safe — two processes rolling the same file races and loses lines.
With a pid in the name, each process only ever rotates its own file and the
reader merges by timestamp. Bounded by ``MAX_BYTES * (BACKUPS + 1)`` per
process; ``/data`` is real host disk that this project's own disk-full runbook
alerts on, so the cap is not optional.

Timestamps are ISO-8601 **UTC** with an explicit ``Z``. The container ships no
tzdata and gets no TZ from the Supervisor, so local time is not available —
making that explicit beats emitting an ambiguous naive timestamp.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import time
from contextvars import ContextVar

from .logsafe import redact

# Per-request correlation id, set by the Flask hook and injected into records.
# A ContextVar (not thread-local) so it survives async and is per-request.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 1
LOG_DIR_NAME = "logs"

_configured = False


class UTCFormatter(logging.Formatter):
    """ISO-8601 UTC with a literal Z, so a reader never has to guess the offset."""

    converter = time.gmtime

    def formatTime(self, record, datefmt=None):  # noqa: N802 - stdlib signature
        base = time.strftime("%Y-%m-%dT%H:%M:%S", self.converter(record.created))
        return f"{base}.{int(record.msecs):03d}Z"


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every record (``-`` outside a request)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


class RedactingFilter(logging.Filter):
    """Strip credentials from every record, whoever wrote it.

    This is a backstop, not a replacement for redacting at the raise site. Many
    call sites log a bare exception (``_LOGGER.exception``, provider/barcode
    error paths), and a driver error can carry a full DSN including its
    password. Fixing those one at a time leaves the next one unguarded; this
    catches all of them, including code written later.

    ``extra_secrets`` are the deployment's own resolved secret values, so a
    short custom token that matches no generic pattern is still removed.
    """

    def __init__(self, extra_secrets: tuple[str, ...] = ()):
        super().__init__()
        self._extra = extra_secrets

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken format string must not kill logging
            return True
        cleaned = redact(message, self._extra)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        if record.exc_text:
            record.exc_text = redact(record.exc_text, self._extra)
        return True


def _secret_values(settings) -> tuple[str, ...]:
    """The deployment's own secrets, for the redactor. Never logged, obviously."""
    if settings is None:
        return ()
    from .settings import FIELDS

    out = []
    for f in FIELDS:
        if not f.secret:
            continue
        value = settings.values.get(f.name)
        if isinstance(value, str) and value:
            out.append(value)
    return tuple(out)


def _prune_dead_process_logs(log_dir: str) -> None:
    """Remove log files whose owning process is gone.

    Without this, every restart leaks another pair of files and the directory
    grows without bound even though each file is individually capped.
    """
    try:
        names = os.listdir(log_dir)
    except OSError:
        return
    for name in names:
        base = name.split(".")[0]
        _, _, pid = base.rpartition("-")
        if not pid.isdigit():
            continue
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            try:
                os.remove(os.path.join(log_dir, name))
            except OSError:
                pass
        except (PermissionError, OSError):
            continue  # alive but not ours, or unreadable — leave it


def configure(settings=None, process: str = "app", force: bool = False) -> str | None:
    """Install handlers. Idempotent; returns the log file path (or None).

    Deliberately not ``logging.basicConfig``: that silently does nothing when a
    handler already exists, and Alembic gets there first during migrations. We
    attach our own handlers and set the level explicitly.
    """
    global _configured
    if _configured and not force:
        return None

    level_name = (getattr(settings, "LOG_LEVEL", None) or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = UTCFormatter(
        "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
    filters = [RequestIdFilter(), RedactingFilter(_secret_values(settings))]

    root = logging.getLogger()
    root.setLevel(level)
    # Drop handlers we installed before (force=True) and Alembic's accidental
    # one, so records are not emitted twice with two different formats.
    for existing in list(root.handlers):
        root.removeHandler(existing)

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    for f in filters:
        stream.addFilter(f)
    root.addHandler(stream)

    path = None
    data_dir = getattr(settings, "data_dir", None) if settings is not None else None
    if data_dir:
        log_dir = os.path.join(data_dir, LOG_DIR_NAME)
        try:
            os.makedirs(log_dir, exist_ok=True)
            _prune_dead_process_logs(log_dir)
            path = os.path.join(log_dir, f"{process}-{os.getpid()}.log")
            file_handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
            file_handler.setFormatter(fmt)
            for f in filters:
                file_handler.addFilter(f)
            root.addHandler(file_handler)
        except OSError as exc:
            # An unwritable data dir must never stop the app from serving; the
            # startup writability check already fails loudly for the real cases.
            path = None
            root.warning("could not open a log file under %s: %s", log_dir, exc)

    _configured = True
    return path
