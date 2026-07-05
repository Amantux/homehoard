from __future__ import annotations

import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from . import services
from .const import DOMAIN
from .coordinator import HomeHoardDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "binary_sensor", "calendar"]

CARD_FILENAME = "homehoard-card.js"
CARD_URL = "/homehoard_static/homehoard-card.js"
_CARD_FLAG = f"{DOMAIN}_card_registered"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the bundled Lovelace card and auto-load it as a frontend resource."""
    if hass.data.get(_CARD_FLAG):
        return
    path = os.path.join(os.path.dirname(__file__), CARD_FILENAME)
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, path, False)]
        )
    except (ImportError, AttributeError):  # older cores
        hass.http.register_static_path(CARD_URL, path, False)

    try:
        from homeassistant.components import frontend
        from homeassistant.loader import async_get_integration

        version = (await async_get_integration(hass, DOMAIN)).version
        frontend.add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    except Exception as err:  # noqa: BLE001 - never block setup over a card
        _LOGGER.warning("HomeHoard: could not auto-register the Lovelace card: %s", err)

    hass.data[_CARD_FLAG] = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = aiohttp_client.async_get_clientsession(hass)
    coordinator = HomeHoardDataUpdateCoordinator(hass, session, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Voice intent ("where is my drill?") + homehoard.locate response service.
    await services.async_register(hass)
    # Ship the custom Lovelace card (type: custom:homehoard-card).
    await _async_register_card(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            services.async_unregister(hass)
    return unload_ok
