from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
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
    async_add_entities([HomeHoardRestockTodoList(coordinator, entry)])


class HomeHoardRestockTodoList(
    CoordinatorEntity[HomeHoardDataUpdateCoordinator], TodoListEntity
):
    """The restock (shopping) list as a native HA to-do list.

    Items mirror ``/api/v1/ha/summary``'s ``restock`` feed — the same policy
    that drives ``GET /api/v1/restock`` and the notification digest, so the
    to-do list can never disagree with the app.

    Checking an item off is deliberately NOT an inventory write. A checkoff
    means "I bought it", not "it's on the shelf and counted" — silently bumping
    quantities from a to-do tap would fake inventory the user never confirmed
    (how many did they actually buy? which location?). So completion only hides
    the item from this list, locally; the honest update happens when the user
    records the new quantity in HomeHoard, at which point the backend drops the
    item from the restock feed for real. If the quantity is never updated, the
    item reappears once the checkoff memory is reconciled against a feed that
    still lists it — the list nags exactly as long as the inventory says it
    should.
    """

    _attr_has_entity_name = True
    _attr_name = "Restock list"
    _attr_icon = "mdi:cart-outline"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(
        self, coordinator: HomeHoardDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_restock_todo"
        self._attr_device_info = device_info(entry)
        # Item ids the user checked off in HA. Purely local: hides the item
        # from this view until the backend itself stops suggesting it (see the
        # class docstring). Pruned against every refresh so a *new* restock
        # need for the same item resurfaces it.
        self._checked_off: set[str] = set()

    @staticmethod
    def _restock_items(data: dict | None) -> list[dict]:
        return ((data or {}).get("restock") or {}).get("items") or []

    @property
    def todo_items(self) -> list[TodoItem] | None:
        items = self._restock_items(self.coordinator.data)
        current_ids = {str(r["id"]) for r in items if "id" in r}
        # Reconcile: once the backend no longer suggests an item, forget the
        # checkoff so the next genuine restock need shows up again.
        self._checked_off &= current_ids
        return [
            TodoItem(
                summary=f"{r.get('name', '?')} — buy {r.get('suggestedQuantity')}",
                uid=str(r["id"]),
                status=TodoItemStatus.NEEDS_ACTION,
                description=f"On hand: {r.get('onHand')}",
            )
            for r in items
            if "id" in r and str(r["id"]) not in self._checked_off
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Check off = hide locally. Never writes inventory (see class docstring)."""
        if item.uid is None:
            return
        if item.status == TodoItemStatus.COMPLETED:
            self._checked_off.add(item.uid)
        else:
            self._checked_off.discard(item.uid)
        self.async_write_ha_state()
