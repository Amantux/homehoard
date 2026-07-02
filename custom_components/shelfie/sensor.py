from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ShelfieDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class ShelfieSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], object] = lambda data: None


SENSORS: tuple[ShelfieSensorDescription, ...] = (
    ShelfieSensorDescription(
        key="total_items",
        name="Total items",
        icon="mdi:package-variant-closed",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("stats", {}).get("totalItems"),
    ),
    ShelfieSensorDescription(
        key="total_value",
        name="Total value",
        icon="mdi:cash",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("stats", {}).get("totalItemPrice"),
    ),
    ShelfieSensorDescription(
        key="total_locations",
        name="Locations",
        icon="mdi:map-marker",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("stats", {}).get("totalLocations"),
    ),
    ShelfieSensorDescription(
        key="total_labels",
        name="Labels",
        icon="mdi:tag-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("stats", {}).get("totalLabels"),
    ),
    ShelfieSensorDescription(
        key="total_with_warranty",
        name="Items under warranty",
        icon="mdi:shield-check",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("stats", {}).get("totalWithWarranty"),
    ),
    ShelfieSensorDescription(
        key="status",
        name="Status",
        icon="mdi:heart-pulse",
        value_fn=lambda d: "online" if d.get("status", {}).get("health") else "offline",
    ),
)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Shelfie",
        manufacturer="Shelfie",
        model="Shelfie inventory",
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: ShelfieDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ShelfieSensor(coordinator, entry, desc) for desc in SENSORS
    )


class ShelfieSensor(
    CoordinatorEntity[ShelfieDataUpdateCoordinator], SensorEntity
):
    _attr_has_entity_name = True
    entity_description: ShelfieSensorDescription

    def __init__(
        self,
        coordinator: ShelfieDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ShelfieSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data or {})
