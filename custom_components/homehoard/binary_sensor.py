from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HomeHoardDataUpdateCoordinator
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: HomeHoardDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HomeHoardOnlineSensor(coordinator, entry)])


class HomeHoardOnlineSensor(
    CoordinatorEntity[HomeHoardDataUpdateCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_online"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success and bool(
            (self.coordinator.data or {}).get("health")
        )
