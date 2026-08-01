"""Pluggable AI provider interface.

HomeHoard talks to LLMs through a single small interface so the app code never
depends on a specific vendor. Three adapters ship: Ollama, OpenAI-compatible, and
Claude (see the sibling modules); the active one is chosen by ``HBOX_AI_PROVIDER``
or the in-app setting.

Two operations cover every feature:

* ``complete_json`` — one-shot "return structured data" (item enrichment, barcode
  identification, categorization, clustering). Portable across vendors by prompting
  for JSON and parsing, rather than relying on any one vendor's structured-output API.
* ``chat`` — a conversational turn with optional tool-calling, used by the chat
  assistant. Tool wiring is exercised by the chat milestone; the shape is defined
  here so all adapters implement it uniformly.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ProviderError(RuntimeError):
    """Raised when a provider is misconfigured or the upstream call fails."""


# Anything that looks like a credential in upstream error text. Providers echo
# the failing request back in exception strings, which can carry the API key
# (header or query string) or a URL with embedded userinfo.
_SECRETISH = re.compile(
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
_MAX_UPSTREAM_DETAIL = 200


def safe_upstream_detail(exc: BaseException, limit: int = _MAX_UPSTREAM_DETAIL) -> str:
    """A short, credential-free summary of an upstream failure.

    Provider SDK/HTTP exceptions get surfaced to API clients (the endpoints
    return ``str(exc)``), so the raw text must never carry an API key, a URL
    with embedded userinfo, or a full response body. Keeps the exception type
    plus a redacted, truncated message — enough to debug "connection refused"
    vs "401 unauthorized" without leaking the secret that caused it.
    """
    detail = _SECRETISH.sub("[redacted]", str(exc) or "")
    detail = " ".join(detail.split())  # collapse multi-line response bodies
    if len(detail) > limit:
        detail = detail[:limit].rstrip() + "…"
    kind = type(exc).__name__
    return f"{kind}: {detail}" if detail else kind


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatResult:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class AIProvider(ABC):
    """Common surface implemented by every provider adapter."""

    #: short stable id, e.g. "ollama" | "openai" | "claude"
    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        """True when this provider has the config (key/host/model) it needs."""

    @abstractmethod
    def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        """Return the model's raw text for a single system+user exchange."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[dict] | None = None,
        max_tokens: int = 2048,
    ) -> ChatResult:
        """One conversational turn. ``messages`` is a list of {role, content}.

        ``tools`` uses the neutral schema ``[{name, description, parameters}]``
        (JSON-Schema ``parameters``); adapters translate to their own format.
        """

    def chat_stream(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[dict] | None = None,
        max_tokens: int = 2048,
    ):
        """Stream one conversational turn.

        Yields ``{"type": "delta", "text": str}`` events as text arrives, then
        exactly one terminal ``{"type": "final", "result": ChatResult}`` carrying
        the full content + any tool calls. The default has no real streaming — it
        runs the blocking :meth:`chat` and emits its whole content as one delta;
        adapters override this with true token streaming.
        """
        result = self.chat(messages, system=system, tools=tools, max_tokens=max_tokens)
        if result.content:
            yield {"type": "delta", "text": result.content}
        yield {"type": "final", "result": result}

    def complete_json(
        self, prompt: str, system: str = "", max_tokens: int = 4096
    ) -> dict:
        """Prompt for JSON and return the parsed object.

        A JSON-only instruction is appended to whatever ``system`` is given so
        the contract holds regardless of vendor.
        """
        sys = (system + "\n\n" if system else "") + (
            "Respond with a single valid JSON value and nothing else — no prose, "
            "no markdown fences, no explanation."
        )
        raw = self._complete(sys, prompt, max_tokens)
        return extract_json(raw)


def extract_json(text: str) -> dict:
    """Parse a JSON *object* from model output, tolerating fences/prose.

    Raises ``ProviderError`` on anything that isn't a JSON object — including
    valid-but-wrong-shape output like a bare array or scalar — so callers never
    have to defend against a non-dict return.
    """
    text = (text or "").strip()
    # Strip a ```json … ``` fence if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    parsed = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Last resort: grab the outermost {...} span.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    f"model did not return valid JSON: {exc}"
                ) from exc
    if not isinstance(parsed, dict):
        raise ProviderError("model did not return a JSON object")
    return parsed
