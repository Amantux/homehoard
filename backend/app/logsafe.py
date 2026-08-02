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

import re

_BAD = str.maketrans({"\r": "\\r", "\n": "\\n", "\t": "\\t"})

REDACTED = "[redacted]"

# Values that must never appear in a log line, whoever wrote it. This lives here
# rather than in the AI provider layer because it is now applied in two places:
# at the raise site (services/ai/base.safe_upstream_detail, for text that reaches
# an API client) AND as a logging filter over every record we write, which is the
# backstop for the call sites that log a raw exception without thinking about it.
SECRETISH = re.compile(
    r"""(?ix)
    ( (?:sk|rk|pk|xai|gsk)[-_][A-Za-z0-9_\-]{8,}   # OpenAI/Anthropic/xAI/Groq keys
    | AIza[A-Za-z0-9_\-]{10,}                      # Google API keys
    | Bearer\s+[A-Za-z0-9._\-]{8,}                 # Authorization header values
    # name=value / "name": "value" — the optional quotes matter: a JSON body
    # renders as `"api_key": "…"`, which a bare name[=:] pattern never matches.
    # The optional `Bearer ` inside the VALUE matters: without it this arm
    # matches `Authorization: Bearer` and stops at the space, leaving the token.
    | (?:api[-_]?key|access[-_]?token|authorization|key|token)
      ["']?\s*[=:]\s*["']?(?:Bearer\s+)?[^"'\s,}&]+
    | [A-Za-z][A-Za-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@   # scheme://user:pass@
    # Catch-all for high-entropy blobs (Ollama Cloud / bare hex or base64 keys)
    # that match no vendor prefix. Long enough not to eat ordinary words.
    | \b[A-Za-z0-9_\-]{40,}\b
    )""",
)


def scrub(value, limit: int = 200) -> str:
    """Return `value` as a single-line string safe to log.

    CR/LF/TAB become visible escapes rather than real control characters, and
    over-long values are truncated so one request can't flood the log.
    """
    text = str(value if value is not None else "").translate(_BAD)
    return text if len(text) <= limit else text[:limit] + "…"


def redact(text: str, extra: tuple[str, ...] = ()) -> str:
    """Strip anything that looks like a credential out of `text`.

    ``extra`` carries the deployment's OWN secret values (resolved settings), so
    a key that matches no generic pattern — a short custom token, a password
    inside a DSN — is still removed. Longest first, so a value that contains
    another is not partially replaced.
    """
    for value in sorted((v for v in extra if v and len(v) >= 6), key=len, reverse=True):
        text = text.replace(value, REDACTED)
    return SECRETISH.sub(REDACTED, text)


def mask_email(value) -> str:
    """`alex@example.com` -> `a***@example.com`.

    Login events are worth logging; the full address is not. It is personal
    data, it lands in a file the debug tooling can read, and no consumer of
    these logs needs more than "which account, roughly".
    """
    text = scrub(value, limit=120)
    local, _, domain = text.partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"
