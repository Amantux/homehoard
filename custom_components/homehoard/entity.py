from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """One device card grouping all HomeHoard entities from a config entry."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="HomeHoard",
        manufacturer="HomeHoard",
        model="Home inventory",
        configuration_url=f"{entry.data.get('host')}:{entry.data.get('port')}",
    )
