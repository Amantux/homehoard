"""Anthropic Claude provider.

Uses the official ``anthropic`` SDK. Model IDs and call shape confirmed against the
claude-api reference (not memory): default model ``claude-opus-4-8``; requests go
through ``client.messages.create`` with ``system`` as a top-level parameter.
"""
from __future__ import annotations

from .base import AIProvider, ChatResult, ProviderError, ToolCall


class ClaudeProvider(AIProvider):
    name = "claude"

    def __init__(self, eff):
        self.api_key = eff.ANTHROPIC_API_KEY
        self.model = eff.CLAUDE_MODEL
        self.timeout = float(eff.AI_TIMEOUT_SECONDS or 60)
        self._client = None

    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - dependency missing
                raise ProviderError("anthropic SDK not installed") from exc
            self._client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)
        return self._client

    def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        client = self._get_client()
        resp = client.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in resp.content if b.type == "text")

    def chat(self, messages, system="", tools=None, max_tokens=2048) -> ChatResult:
        client = self._get_client()
        kwargs = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {"name": t["name"], "description": t.get("description", ""),
                 "input_schema": t.get("parameters", {"type": "object"})}
                for t in tools
            ]
        resp = client.messages.create(**kwargs)
        out = ChatResult()
        for block in resp.content:
            if block.type == "text":
                out.content += block.text
            elif block.type == "tool_use":
                out.tool_calls.append(ToolCall(
                    id=block.id, name=block.name, arguments=dict(block.input)))
        return out
