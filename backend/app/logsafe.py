"""Make attacker-controlled values safe to write into a log line.

Log files are parsed by humans and tools that treat one line as one event, so a
value containing CR/LF can forge an entire fake entry ("log injection"). Request
attributes are fully attacker-controlled — ``request.path`` most obviously — and
land in our auth/login warnings.

Note ``%r`` already neutralises this (``repr`` escapes newlines), so use that
where a quoted value reads well; ``scrub()`` is for the ``%s`` cases where the
quotes would be noise.
"""
from __future__ import annotations

_BAD = str.maketrans({"\r": "\\r", "\n": "\\n", "\t": "\\t"})


def scrub(value, limit: int = 200) -> str:
    """Return `value` as a single-line string safe to log.

    CR/LF/TAB become visible escapes rather than real control characters, and
    over-long values are truncated so one request can't flood the log.
    """
    text = str(value if value is not None else "").translate(_BAD)
    return text if len(text) <= limit else text[:limit] + "…"
