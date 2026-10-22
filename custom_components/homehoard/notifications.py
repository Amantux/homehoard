"""Actionable notification handlers for HomeHoard.

This module listens for mobile_app_notification_action events and maps action
payloads to coordinator methods, enabling one-tap actions from Home Assistant
notifications without opening the HomeHoard app.

Supported actions:
  - hoard:checkin:<item_name> - Check an item back in
  - hoard:checkout:<item_name> - Check an item out
  - hoard:maintenance_done:<item_id>:<entry_id> - Mark maintenance entry complete
  - hoard:restock:<item_id> - Record a reorder intent for low-stock item
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import HomeHoardDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Action prefixes used in notification payloads
ACTION_CHECKIN = "hoard:checkin:"
ACTION_CHECKOUT = "hoard:checkout:"
ACTION_MAINTENANCE_DONE = "hoard:maintenance_done:"
ACTION_REORDER = "hoard:restock:"


def _parse_checkin_action(action: str) -> str | None:
    """Extract item name from checkin action payload."""
    if action.startswith(ACTION_CHECKIN):
        return action[len(ACTION_CHECKIN) :]
    return None


def _parse_checkout_action(action: str) -> str | None:
    """Extract item name from checkout action payload."""
    if action.startswith(ACTION_CHECKOUT):
        return action[len(ACTION_CHECKOUT) :]
    return None


def _parse_maintenance_done_action(action: str) -> tuple[str, str] | None:
    """Extract item_id and entry_id from maintenance_done action payload."""
    if action.startswith(ACTION_MAINTENANCE_DONE):
        rest = action[len(ACTION_MAINTENANCE_DONE) :]
        parts = rest.split(":")
        if len(parts) == 2:
            return parts[0], parts[1]
    return None


def _parse_reorder_action(action: str) -> str | None:
    """Extract item_id from reorder action payload."""
    if action.startswith(ACTION_REORDER):
        return action[len(ACTION_REORDER) :]
    return None


@callback
def async_setup(hass: HomeAssistant) -> None:
    """Set up the actionable notification listener."""

    @callback
    def handle_notification_action(event: dict) -> None:
        """Handle a mobile_app_notification_action event."""
        action = event.get("action")
        if not action:
            return

        coordinator = _get_coordinator(hass)
        if coordinator is None:
            _LOGGER.warning("HomeHoard coordinator not available for action: %s", action)
            return

        # Route to appropriate handler
        if action.startswith(ACTION_CHECKIN):
            item_name = _parse_checkin_action(action)
            if item_name:
                hass.async_create_task(_handle_checkin(hass, coordinator, item_name))
        elif action.startswith(ACTION_CHECKOUT):
            item_name = _parse_checkout_action(action)
            if item_name:
                hass.async_create_task(_handle_checkout(hass, coordinator, item_name))
        elif action.startswith(ACTION_MAINTENANCE_DONE):
            result = _parse_maintenance_done_action(action)
            if result:
                item_id, entry_id = result
                hass.async_create_task(
                    _handle_maintenance_done(hass, coordinator, item_id, entry_id)
                )
        elif action.startswith(ACTION_REORDER):
            item_id = _parse_reorder_action(action)
            if item_id:
                hass.async_create_task(_handle_reorder(hass, coordinator, item_id))

    hass.bus.async_listen("mobile_app_notification_action", handle_notification_action)


def _get_coordinator(hass: HomeAssistant) -> HomeHoardDataUpdateCoordinator | None:
    """Get the first available HomeHoard coordinator."""
    for value in hass.data.get(DOMAIN, {}).values():
        if hasattr(value, "search"):
            return value
    return None


async def _handle_checkin(
    hass: HomeAssistant, coordinator: HomeHoardDataUpdateCoordinator, item_name: str
) -> None:
    """Handle check-in action."""
    result = await coordinator.checkin(item_name)
    status = result.get("status")
    if status in ("checked_in", "already_in"):
        _LOGGER.info("Check-in action completed for: %s", item_name)
    else:
        _LOGGER.warning("Check-in action failed for %s: %s", item_name, result)


async def _handle_checkout(
    hass: HomeAssistant, coordinator: HomeHoardDataUpdateCoordinator, item_name: str
) -> None:
    """Handle check-out action."""
    result = await coordinator.checkout(item_name)
    status = result.get("status")
    if status in ("checked_out", "already_out"):
        _LOGGER.info("Check-out action completed for: %s", item_name)
    else:
        _LOGGER.warning("Check-out action failed for %s: %s", item_name, result)


async def _handle_maintenance_done(
    hass: HomeAssistant,
    coordinator: HomeHoardDataUpdateCoordinator,
    item_id: str,
    entry_id: str,
) -> None:
    """Handle marking maintenance entry as done."""
    # Use the coordinator's API request helper to complete the maintenance entry
    path = f"/api/v1/items/{item_id}/maintenance/{entry_id}"
    try:
        result = await coordinator._post_json(path, {"completedDate": "now"})
        if result:
            _LOGGER.info(
                "Maintenance done action completed for entry %s (item %s)", entry_id, item_id
            )
        else:
            _LOGGER.warning(
                "Maintenance done action failed for entry %s (item %s)", entry_id, item_id
            )
    except Exception as err:
        _LOGGER.error(
            "Error completing maintenance entry %s: %s", entry_id, err
        )


async def _handle_reorder(
    hass: HomeAssistant, coordinator: HomeHoardDataUpdateCoordinator, item_id: str
) -> None:
    """Handle reorder action for a low-stock item."""
    # Record reorder intent by checking out the item (simulating it being used up)
    # or by creating a restock entry via the API
    try:
        # First, get the item to verify it exists and get its name
        item_data = await coordinator._get_json(f"/api/v1/items/{item_id}")
        item_name = item_data.get("name", item_id)

        # For now, log the reorder intent
        # In a full implementation, this could create a shopping list entry
        _LOGGER.info("Reorder action recorded for item: %s (id: %s)", item_name, item_id)
    except Exception as err:
        _LOGGER.error("Error processing reorder for item %s: %s", item_id, err)
