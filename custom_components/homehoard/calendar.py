from __future__ import annotations

from datetime import datetime, timedelta

from aiohttp import ClientError, ClientTimeout
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_HOST, CONF_PORT, CONF_TOKEN, DEFAULT_CALENDAR_PATH
from .entity import device_info
from .helpers import build_url

_TIMEOUT = ClientTimeout(total=10)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([HomeHoardCalendar(hass, entry)])


class HomeHoardCalendar(CalendarEntity):
    """Warranty expirations and scheduled maintenance as a calendar."""

    _attr_has_entity_name = True
    _attr_name = "Warranties & maintenance"
    _attr_icon = "mdi:calendar-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._session = aiohttp_client.async_get_clientsession(hass)
        self._url = build_url(
            entry.data[CONF_HOST], int(entry.data[CONF_PORT]), DEFAULT_CALENDAR_PATH
        )
        # Auth header for auth-enabled (standalone) servers; empty for the add-on.
        token = entry.data.get(CONF_TOKEN, "")
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_device_info = device_info(entry)
        self._next: CalendarEvent | None = None

    @property
    def event(self) -> CalendarEvent | None:
        return self._next

    async def async_update(self) -> None:
        now = dt_util.now()
        events = await self._fetch(now, now + timedelta(days=365))
        self._next = events[0] if events else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return await self._fetch(start_date, end_date)

    async def _fetch(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        params = {"start": start.date().isoformat(), "end": end.date().isoformat()}
        try:
            async with self._session.get(
                self._url, params=params, headers=self._headers, timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                raw = await resp.json()
        except (ClientError, TimeoutError):
            return []

        events: list[CalendarEvent] = []
        for e in raw:
            try:
                start_d = datetime.fromisoformat(e["start"]).date()
                end_d = datetime.fromisoformat(e["end"]).date()
            except (KeyError, ValueError):
                continue
            events.append(
                CalendarEvent(
                    start=start_d,
                    end=end_d,
                    summary=e.get("summary", ""),
                    uid=e.get("uid"),
                    description=e.get("category"),
                )
            )
        return events
