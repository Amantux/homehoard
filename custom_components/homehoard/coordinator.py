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
    CONF_UPDATE_INTERVAL,
    DEFAULT_STATS_PATH,
    DEFAULT_STATUS_PATH,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .helpers import build_url

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = ClientTimeout(total=10)


class HomeHoardDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the HomeHoard API for health + group statistics."""

    def __init__(
        self, hass: HomeAssistant, session: ClientSession, entry: ConfigEntry
    ) -> None:
        self._session = session
        host = entry.data[CONF_HOST]
        port = int(entry.data[CONF_PORT])
        self._status_url = build_url(host, port, DEFAULT_STATUS_PATH)
        self._stats_url = build_url(host, port, DEFAULT_STATS_PATH)
        interval = int(entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=interval)
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            status = await self._get(self._status_url)
            stats = await self._get(self._stats_url)
        except (ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Error fetching HomeHoard data: {err}") from err
        return {"status": status, "stats": stats}

    async def _get(self, url: str) -> dict[str, Any]:
        async with self._session.get(url, timeout=_TIMEOUT) as response:
            response.raise_for_status()
            return await response.json()
