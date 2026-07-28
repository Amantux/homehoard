"""OpenAI provider (Chat Completions).

Uses the official ``openai`` SDK's ``chat.completions`` surface, which every
OpenAI-compatible server also speaks — set a base URL to point at a local SLM
runtime (LM Studio, vLLM, llama.cpp, LocalAI, Ollama's ``/v1``) or hosted OpenAI.
"""
from __future__ import annotations

import json

from .base import AIProvider, ChatResult, ProviderError, ToolCall


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self, eff):
        self.api_key = eff.OPENAI_API_KEY
        self.model = eff.OPENAI_MODEL
        self.timeout = float(eff.AI_TIMEOUT_SECONDS or 60)
        self.base_url = (eff.OPENAI_BASE_URL or "").rstrip("/") or None
        self._client = None

    def available(self) -> bool:
        # A custom base URL (local SLM) often needs no key; hosted OpenAI does.
        return bool(self.model and (self.api_key or self.base_url))

    def _get_client(self):
        if self._client is None:
            try:
                import openai
            except ImportError as exc:  # pragma: no cover - dependency missing
                raise ProviderError("openai SDK not installed") from exc
            kwargs = {"api_key": self.api_key or "sk-none", "timeout": self.timeout}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = openai.OpenAI(**kwargs)
        return self._client

    def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        client = self._get_client()
        resp = client.chat.completions.create(
            model=self.model, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}])
        return resp.choices[0].message.content or ""

    def chat(self, messages, system="", tools=None, max_tokens=2048) -> ChatResult:
        client = self._get_client()
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        kwargs = {"model": self.model, "max_tokens": max_tokens, "messages": msgs}
        if tools:
            kwargs["tools"] = [
                {"type": "function", "function": {
                    "name": t["name"], "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object"})}}
                for t in tools
            ]
        resp = client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        out = ChatResult(content=msg.content or "")
        for call in msg.tool_calls or []:
            out.tool_calls.append(ToolCall(
                id=call.id, name=call.function.name,
                arguments=json.loads(call.function.arguments or "{}")))
        return out

    def chat_stream(self, messages, system="", tools=None, max_tokens=2048):
        """True token streaming via Chat Completions ``stream=True``. Text arrives
        as ``delta.content``; tool calls arrive fragmented across chunks and are
        reassembled by index before their JSON arguments are parsed."""
        client = self._get_client()
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        kwargs = {"model": self.model, "max_tokens": max_tokens,
                  "messages": msgs, "stream": True}
        if tools:
            kwargs["tools"] = [
                {"type": "function", "function": {
                    "name": t["name"], "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object"})}}
                for t in tools
            ]
        content = ""
        frags: dict[int, dict] = {}
        try:
            for chunk in client.chat.completions.create(**kwargs):
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content += delta.content
                    yield {"type": "delta", "text": delta.content}
                for tc in (delta.tool_calls or []):
                    slot = frags.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments
        except Exception as exc:  # noqa: BLE001 - normalize SDK/HTTP errors
            raise ProviderError(f"openai request failed: {exc}") from exc
        out = ChatResult(content=content)
        for idx in sorted(frags):
            f = frags[idx]
            try:
                args = json.loads(f["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            out.tool_calls.append(ToolCall(
                id=f["id"] or f"call_{idx}", name=f["name"], arguments=args))
        yield {"type": "final", "result": out}
