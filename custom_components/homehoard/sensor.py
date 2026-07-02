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
from .coordinator import HomeHoardDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class HomeHoardSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], object] = lambda data: None


SENSORS: tuple[HomeHoardSensorDescription, ...] = (
    HomeHoardSensorDescription(
        key="total_items",
        name="Total items",
        icon="mdi:package-variant-closed",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("stats", {}).get("totalItems"),
    ),
    HomeHoardSensorDescription(
        key="total_value",
        name="Total value",
        icon="mdi:cash",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("stats", {}).get("totalItemPrice"),
    ),
    HomeHoardSensorDescription(
        key="total_locations",
        name="Locations",
        icon="mdi:map-marker",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("stats", {}).get("totalLocations"),
    ),
    HomeHoardSensorDescription(
        key="total_labels",
        name="Labels",
        icon="mdi:tag-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("stats", {}).get("totalLabels"),
    ),
    HomeHoardSensorDescription(
        key="total_with_warranty",
        name="Items under warranty",
        icon="mdi:shield-check",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("stats", {}).get("totalWithWarranty"),
    ),
    HomeHoardSensorDescription(
        key="status",
        name="Status",
        icon="mdi:heart-pulse",
        value_fn=lambda d: "online" if d.get("status", {}).get("health") else "offline",
    ),
)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="HomeHoard",
        manufacturer="HomeHoard",
        model="HomeHoard inventory",
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: HomeHoardDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HomeHoardSensor(coordinator, entry, desc) for desc in SENSORS
    )


class HomeHoardSensor(
    CoordinatorEntity[HomeHoardDataUpdateCoordinator], SensorEntity
):
    _attr_has_entity_name = True
    entity_description: HomeHoardSensorDescription

    def __init__(
        self,
        coordinator: HomeHoardDataUpdateCoordinator,
        entry: ConfigEntry,
        description: HomeHoardSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data or {})
