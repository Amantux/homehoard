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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HomeHoardDataUpdateCoordinator
from .entity import device_info


@dataclass(frozen=True, kw_only=True)
class HomeHoardSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], object] = lambda data: None
    attrs_fn: Callable[[dict], dict] | None = None


def _totals(d: dict) -> dict:
    return d.get("totals", {})


SENSORS: tuple[HomeHoardSensorDescription, ...] = (
    HomeHoardSensorDescription(
        key="total_items", name="Total items", icon="mdi:package-variant-closed",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _totals(d).get("items"),
    ),
    HomeHoardSensorDescription(
        key="total_value", name="Total value", icon="mdi:cash",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _totals(d).get("value"),
    ),
    HomeHoardSensorDescription(
        key="insured_value", name="Insured value", icon="mdi:shield-account",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _totals(d).get("insuredValue"),
    ),
    HomeHoardSensorDescription(
        key="total_locations", name="Locations", icon="mdi:map-marker",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _totals(d).get("locations"),
    ),
    HomeHoardSensorDescription(
        key="total_bins", name="Bins", icon="mdi:archive",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _totals(d).get("bins"),
    ),
    HomeHoardSensorDescription(
        key="total_labels", name="Labels", icon="mdi:tag-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _totals(d).get("labels"),
    ),
    HomeHoardSensorDescription(
        key="warranties_expiring", name="Warranties expiring (30d)",
        icon="mdi:shield-alert", state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("warrantiesExpiring", {}).get("days30"),
        attrs_fn=lambda d: {
            "next_90_days": d.get("warrantiesExpiring", {}).get("days90"),
            "items": d.get("warrantiesExpiring", {}).get("items", []),
        },
    ),
    HomeHoardSensorDescription(
        key="maintenance_overdue", name="Maintenance overdue",
        icon="mdi:wrench-clock", state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("maintenance", {}).get("overdue"),
        attrs_fn=lambda d: {
            "upcoming_30_days": d.get("maintenance", {}).get("upcoming30"),
            "entries": d.get("maintenance", {}).get("entries", []),
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: HomeHoardDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(HomeHoardSensor(coordinator, entry, d) for d in SENSORS)


class HomeHoardSensor(
    CoordinatorEntity[HomeHoardDataUpdateCoordinator], SensorEntity
):
    _attr_has_entity_name = True
    entity_description: HomeHoardSensorDescription

    def __init__(self, coordinator, entry, description) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self):
        if self.entity_description.attrs_fn:
            return self.entity_description.attrs_fn(self.coordinator.data or {})
        return None
