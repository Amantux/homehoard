"""Ollama provider — local and private by default.

Talks to an Ollama server's ``/api/chat`` endpoint over HTTP. Default host is
``http://localhost:11434``. A plain local server needs no key; set an Ollama API
key to send a bearer token for Ollama Cloud or a secured/proxied instance. Any
OpenAI-compatible local SLM should use the ``openai`` provider with a base URL.
"""
from __future__ import annotations

import json

import httpx

from .base import AIProvider, ChatResult, ProviderError, ToolCall


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self, eff):
        self.host = (eff.OLLAMA_HOST or "").rstrip("/")
        self.model = eff.OLLAMA_MODEL
        self.timeout = float(eff.AI_TIMEOUT_SECONDS or 60)
        self.api_key = getattr(eff, "OLLAMA_API_KEY", "") or ""

    def available(self) -> bool:
        return bool(self.host and self.model)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _post(self, payload: dict) -> dict:
        try:
            r = httpx.post(f"{self.host}/api/chat", json=payload,
                           headers=self._headers(), timeout=self.timeout)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama request failed: {exc}") from exc
        return r.json()

    def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        data = self._post({
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"num_predict": max_tokens},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        })
        return (data.get("message") or {}).get("content", "")

    def chat(self, messages, system="", tools=None, max_tokens=2048) -> ChatResult:
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"num_predict": max_tokens},
            "messages": msgs,
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {
                    "name": t["name"], "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object"})}}
                for t in tools
            ]
        data = self._post(payload)
        msg = data.get("message") or {}
        out = ChatResult(content=msg.get("content", ""))
        for i, call in enumerate(msg.get("tool_calls") or []):
            fn = call.get("function", {})
            out.tool_calls.append(ToolCall(
                id=f"call_{i}", name=fn.get("name", ""),
                arguments=fn.get("arguments", {}) or {}))
        return out

    def chat_stream(self, messages, system="", tools=None, max_tokens=2048):
        """True token streaming via Ollama's NDJSON stream (one JSON object per
        line, each with an incremental ``message.content``; tool calls arrive in
        the message object, typically on the final chunk)."""
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        payload = {
            "model": self.model,
            "stream": True,
            "options": {"num_predict": max_tokens},
            "messages": msgs,
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {
                    "name": t["name"], "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object"})}}
                for t in tools
            ]
        content = ""
        raw_calls: list[dict] = []
        try:
            with httpx.stream("POST", f"{self.host}/api/chat", json=payload,
                              headers=self._headers(), timeout=self.timeout) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    obj = json.loads(line)
                    msg = obj.get("message") or {}
                    piece = msg.get("content") or ""
                    if piece:
                        content += piece
                        yield {"type": "delta", "text": piece}
                    for call in msg.get("tool_calls") or []:
                        raw_calls.append(call)
                    if obj.get("done"):
                        break
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama request failed: {exc}") from exc
        out = ChatResult(content=content)
        for i, call in enumerate(raw_calls):
            fn = call.get("function", {})
            out.tool_calls.append(ToolCall(
                id=f"call_{i}", name=fn.get("name", ""),
                arguments=fn.get("arguments", {}) or {}))
        yield {"type": "final", "result": out}


class OllamaCloudProvider(OllamaProvider):
    """Ollama's hosted cloud (https://ollama.com). Same wire protocol as a local
    Ollama server (/api/chat, /api/tags, bearer auth) but pinned to the cloud host
    and REQUIRING an API key. Host/model/key come from the OLLAMA_CLOUD_* attrs on
    the effective config, so the cloud key is never shared with a local Ollama."""

    name = "ollama_cloud"

    def __init__(self, eff):
        self.host = (getattr(eff, "OLLAMA_CLOUD_HOST", "") or "https://ollama.com").rstrip("/")
        self.model = getattr(eff, "OLLAMA_CLOUD_MODEL", "") or ""
        self.timeout = float(getattr(eff, "AI_TIMEOUT_SECONDS", 60) or 60)
        self.api_key = getattr(eff, "OLLAMA_CLOUD_API_KEY", "") or ""

    def available(self) -> bool:
        # Unlike a plain local server, the cloud requires a key.
        return bool(self.host and self.model and self.api_key)
