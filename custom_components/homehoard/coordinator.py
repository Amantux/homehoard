from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_SEARCH_PATH,
    DEFAULT_SUMMARY_PATH,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .helpers import build_url

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = ClientTimeout(total=10)


class HomeHoardDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the HomeHoard ``/ha/summary`` endpoint (totals + attention counts)."""

    def __init__(
        self, hass: HomeAssistant, session: ClientSession, entry: ConfigEntry
    ) -> None:
        self._session = session
        self.host = entry.data[CONF_HOST]
        self.port = int(entry.data[CONF_PORT])
        # Long-lived API token for auth-enabled (standalone) servers. Empty for
        # the add-on, which runs auth-disabled behind ingress.
        token = entry.data.get(CONF_TOKEN, "")
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._summary_url = build_url(self.host, self.port, DEFAULT_SUMMARY_PATH)
        interval = int(entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=interval)
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            async with self._session.get(
                self._summary_url, headers=self._headers, timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except (ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Error fetching HomeHoard summary: {err}") from err

    async def search(self, query: str, types: str = "item,bin,location") -> list[dict]:
        """Search items/bins/locations — used by the voice intent and service."""
        url = build_url(self.host, self.port, DEFAULT_SEARCH_PATH)
        try:
            async with self._session.get(
                url,
                params={"q": query, "types": types},
                headers=self._headers,
                timeout=_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except (ClientError, asyncio.TimeoutError):
            return []
        return data.get("results", [])

    async def _get_json(self, path: str, params: dict | None = None):
        url = build_url(self.host, self.port, path)
        async with self._session.get(
            url, params=params or {}, headers=self._headers, timeout=_TIMEOUT
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def contents(self, name: str) -> dict:
        """List what's inside a named bin or location (voice: 'what's in X')."""
        results = await self.search(name, types="bin,location")
        target = next(
            (r for r in results if r.get("type") in ("bin", "location")), None
        )
        if not target:
            return {"status": "not_found", "name": name}
        kind = target["type"]
        try:
            detail = await self._get_json(
                f"/api/v1/{'bins' if kind == 'bin' else 'locations'}/{target['id']}"
            )
        except (ClientError, asyncio.TimeoutError):
            return {"status": "error", "name": target["name"]}
        return {
            "status": "ok",
            "name": target["name"],
            "kind": kind,
            "items": [i.get("name") for i in detail.get("items", [])],
            "bins": [b.get("name") for b in detail.get("bins", [])] if kind == "location" else [],
        }

    async def resolve(self, name: str, kind: str = "item") -> dict:
        """Find one item/bin/location from an id or name — never guessing.

        Delegates to HomeHoard's ``/resolve``, which ranks matches by name,
        labels, description and notes and answers with a confidence. That
        endpoint is the single implementation of the policy — the MCP server
        uses it too, so a name resolves the same way by voice, by service call,
        and in the app.

        Returns ``{"status": "ok", "match": {...}}`` when confident, or
        ``needs_clarification`` (with ranked ``candidates`` carrying labels and
        where each one lives) / ``not_found`` / ``error``. Callers must never
        guess on ``needs_clarification`` — acting on a partial name match is how
        the wrong thing gets checked out or moved.
        """
        ident = (name or "").strip()
        if not ident:
            return {"status": "error", "error": "No name or id given."}
        try:
            data = await self._get_json(
                "/api/v1/resolve", {"q": ident, "type": kind}
            )
        except (ClientError, asyncio.TimeoutError):
            return {"status": "error", "error": "Could not reach HomeHoard."}

        confidence = data.get("confidence")
        if confidence == "high":
            return {"status": "ok", "match": data.get("match") or {}}
        if confidence == "low":
            candidates = data.get("candidates") or []
            return {
                "status": "needs_clarification",
                "error": (
                    f"{len(candidates)} {kind}s match '{ident}'. "
                    "Say which one, or pass its id."
                ),
                "candidates": candidates,
            }
        return {"status": "not_found", "name": ident}

    async def checkout(self, name: str) -> dict:
        """Check an item out by name. Returns a status dict for phrasing."""
        found = await self.resolve(name)
        if found["status"] != "ok":
            return found
        item = found["match"]
        path = f"/api/v1/items/{item['id']}/checkout"
        try:
            async with self._session.post(
                build_url(self.host, self.port, path),
                json={},
                headers=self._headers,
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status == 409:
                    return {"status": "already_out", "name": item["name"]}
                resp.raise_for_status()
        except (ClientError, asyncio.TimeoutError):
            return {"status": "error", "name": item["name"]}
        return {"status": "checked_out", "name": item["name"]}

    async def checkin(self, name: str) -> dict:
        """Check an item back in by name. Returns a status dict for phrasing."""
        found = await self.resolve(name)
        if found["status"] != "ok":
            return found
        item = found["match"]
        path = f"/api/v1/items/{item['id']}/checkin"
        try:
            async with self._session.post(
                build_url(self.host, self.port, path),
                json={},
                headers=self._headers,
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status == 409:
                    return {"status": "already_in", "name": item["name"]}
                resp.raise_for_status()
        except (ClientError, asyncio.TimeoutError):
            return {"status": "error", "name": item["name"]}
        return {"status": "checked_in", "name": item["name"]}
