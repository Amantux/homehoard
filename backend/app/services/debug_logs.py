"""Read this instance's own recent log lines back.

The add-on writes one capped log file per process under ``<DATA_DIR>/logs/``
(see ``app/logging_setup``), because stdout is captured by the container runtime
and cannot be read back. This module merges those files and answers "what just
happened", which is what the debug MCP tools expose.

Two safety properties matter here, because the output is handed to a client:

* **Redaction has already happened** at write time — the logging filter strips
  credentials from every record before it reaches the file. This module redacts
  again on the way out anyway: the file may contain lines written before the
  filter existed, or by a future handler that bypasses it, and a defence that
  only works when nothing has gone wrong is not a defence.
* **Bounded work.** Only the tail of each file is read, and the merged result is
  capped, so a caller cannot make the app load ~16MB into memory.
"""
from __future__ import annotations

import os
import re

from ..logsafe import redact

# "2026-08-02T20:13:30.020Z LEVEL logger [request-id] message"
_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+"
    r"(?P<level>[A-Z]+)\s+(?P<logger>\S+)\s+\[(?P<request_id>[^\]]*)\]\s+(?P<message>.*)$"
)

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}

MAX_LIMIT = 500
# Read at most this much from the end of each file. Comfortably more than
# MAX_LIMIT lines, without ever pulling a whole rotated file into memory.
_TAIL_BYTES = 512 * 1024


def _tail(path: str, size: int = _TAIL_BYTES) -> list[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            start = max(0, fh.tell() - size)
            fh.seek(start)
            data = fh.read()
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if start and lines:
        lines = lines[1:]  # first line is probably truncated mid-way
    return lines


def log_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "logs")


def read_recent(
    data_dir: str,
    level: str = "INFO",
    contains: str = "",
    request_id: str = "",
    since: str = "",
    limit: int = 100,
) -> dict:
    """Merged, filtered, redacted recent log lines, oldest first.

    `level` is a minimum (INFO excludes DEBUG). `contains` is a plain substring,
    not a regex — a caller-supplied regex is a denial-of-service waiting to
    happen. `since` is an ISO timestamp prefix compared lexically, which works
    because the format is fixed-width UTC.
    """
    limit = max(1, min(int(limit or 100), MAX_LIMIT))
    threshold = _LEVELS.get((level or "INFO").upper(), 20)
    needle = (contains or "").lower()

    directory = log_dir(data_dir)
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return {"lines": [], "files": 0, "note": "no log directory yet"}

    parsed: list[dict] = []
    for name in names:
        for raw in _tail(os.path.join(directory, name)):
            m = _LINE.match(raw)
            if not m:
                continue  # gunicorn access lines and tracebacks' continuation
            rec = m.groupdict()
            if _LEVELS.get(rec["level"], 0) < threshold:
                continue
            if since and rec["ts"] < since:
                continue
            if request_id and rec["request_id"] != request_id:
                continue
            if needle and needle not in raw.lower():
                continue
            rec["process"] = name.split(".")[0]
            parsed.append(rec)

    parsed.sort(key=lambda r: r["ts"])
    out = parsed[-limit:]
    for rec in out:
        rec["message"] = redact(rec["message"])
    return {"lines": out, "files": len(names), "truncated": len(parsed) > len(out)}


def error_summary(data_dir: str, limit: int = 20) -> dict:
    """Recent WARNING+ lines grouped by message shape.

    Digits and quoted values are collapsed so "job 41 failed" and "job 42
    failed" count as one problem rather than two — the question being answered
    is "what is going wrong repeatedly", not "list every line".
    """
    recent = read_recent(data_dir, level="WARNING", limit=MAX_LIMIT)["lines"]
    groups: dict[str, dict] = {}
    for rec in recent:
        shape = re.sub(r"\d+", "N", rec["message"])[:160]
        entry = groups.setdefault(shape, {"shape": shape, "count": 0, "level": rec["level"],
                                          "lastAt": rec["ts"], "lastRequestId": rec["request_id"]})
        entry["count"] += 1
        if rec["ts"] >= entry["lastAt"]:
            entry["lastAt"] = rec["ts"]
            entry["lastRequestId"] = rec["request_id"]
            entry["level"] = rec["level"]
    ranked = sorted(groups.values(), key=lambda g: (-g["count"], g["lastAt"]))
    return {"groups": ranked[:limit], "considered": len(recent)}
