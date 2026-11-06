"""Actionable notification handlers for HomeHoard.

Listens for ``mobile_app_notification_action`` events and acts on the ones that
carry a ``hoard:`` action, so a phone notification can change inventory without
opening the app:

  - hoard:checkin:<item name or id> - check an item back in
  - hoard:checkout:<item name or id> - check an item out
  - hoard:maintenance_done:<item_id>:<entry_id> - mark a maintenance entry done
  - hoard:restock:<item_id>:<quantity> - "I bought this many": add them to its stock

The action string is untrusted input. The Companion app fires this event through
its mobile_app webhook, ANY Home Assistant user can register a device (admin or
not), and the resulting request runs with the integration's token. So a name only
ever goes through HomeHoard's tiered resolver, where an ambiguous one refuses, an
id has to look like an id before it is put in a URL, and a quantity has to look like
a number before it is sent (the server still decides whether it can be stored).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN
from .services import _first_coordinator

if TYPE_CHECKING:
    from .coordinator import HomeHoardDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"
_UNSUB = f"{DOMAIN}_notifications_unsub"

# Action prefixes used in notification payloads
ACTION_PREFIX = "hoard:"
ACTION_CHECKIN = "hoard:checkin:"
ACTION_CHECKOUT = "hoard:checkout:"
ACTION_MAINTENANCE_DONE = "hoard:maintenance_done:"
ACTION_REORDER = "hoard:restock:"

# Ids are UUIDs, so they never need more than this. The check is what keeps a
# crafted "../../v1/tokens?x=" out of the URL: dot segments are normalised away
# when the request is built and the query swallows the rest of the path, which
# would turn one action into a POST or PUT at any route, with our token.
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
# What a Numeric(12, 3) column can hold, written the way the digest writes it.
_QUANTITY = re.compile(r"[0-9]{1,9}(\.[0-9]{1,3})?")
# Enough to recognise it by. The rest is untrusted and would only grow the log.
_LOG_CHARS = 100


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
        if len(parts) == 2 and all(_ID.fullmatch(part) for part in parts):
            return parts[0], parts[1]
    return None


def _parse_reorder_action(action: str) -> tuple[str, str] | None:
    """Extract item_id and quantity from reorder action payload.

    The quantity is the number the notification showed. Nothing else may decide
    it: by the time of the tap the server's own suggestion can be a different one,
    and what was bought is what the person was told to buy.
    """
    if action.startswith(ACTION_REORDER):
        parts = action[len(ACTION_REORDER) :].split(":")
        if len(parts) == 2 and _ID.fullmatch(parts[0]) and _QUANTITY.fullmatch(parts[1]):
            return parts[0], parts[1]
    return None


def _route(
    action: str,
) -> tuple[Callable[..., Awaitable[None]], tuple[str, ...]] | None:
    """The handler for an action and its arguments, or None if nothing handles it."""
    if item_name := _parse_checkin_action(action):
        return _handle_checkin, (item_name,)
    if item_name := _parse_checkout_action(action):
        return _handle_checkout, (item_name,)
    if ids := _parse_maintenance_done_action(action):
        return _handle_maintenance_done, ids
    if restock := _parse_reorder_action(action):
        return _handle_reorder, restock
    return None


@callback
def async_setup(hass: HomeAssistant) -> None:
    """Listen for notification actions. Called once per entry, listens once."""
    if _UNSUB in hass.data:
        return

    @callback
    def handle_notification_action(event: Event) -> None:
        """Handle a mobile_app_notification_action event."""
        action = event.data.get("action")
        # Every Companion app notification in the house lands here, not just ours.
        if not isinstance(action, str) or not action.startswith(ACTION_PREFIX):
            return

        route = _route(action)
        if route is None:
            _LOGGER.warning("Ignoring unknown HomeHoard action: %r", action[:_LOG_CHARS])
            return

        coordinator = _first_coordinator(hass)
        if coordinator is None:
            _LOGGER.warning(
                "HomeHoard is not set up, ignoring action: %r", action[:_LOG_CHARS]
            )
            return

        handler, args = route
        hass.async_create_task(handler(coordinator, *args))

    hass.data[_UNSUB] = hass.bus.async_listen(
        EVENT_NOTIFICATION_ACTION, handle_notification_action
    )


@callback
def async_unload(hass: HomeAssistant) -> None:
    """Stop listening. Called when the last entry goes away."""
    if unsub := hass.data.pop(_UNSUB, None):
        unsub()


async def _finish(
    coordinator: HomeHoardDataUpdateCoordinator, what: str, result: dict, done: str
) -> None:
    """Log how an action ended. A real change also refreshes the sensors and to-do."""
    status = result.get("status")
    if status == done:
        _LOGGER.info("%s: %s", what, status)
        await coordinator.async_request_refresh()
    else:
        # Refused or failed, so nothing changed and this is the only trace of why.
        _LOGGER.warning("%s: %s", what, status)


async def _handle_checkin(
    coordinator: HomeHoardDataUpdateCoordinator, item_name: str
) -> None:
    """Handle check-in action. The name is untrusted: repr() keeps it on one log line."""
    result = await coordinator.checkin(item_name)
    await _finish(
        coordinator, f"Check-in of {item_name[:_LOG_CHARS]!r}", result, "checked_in"
    )


async def _handle_checkout(
    coordinator: HomeHoardDataUpdateCoordinator, item_name: str
) -> None:
    """Handle check-out action. The name is untrusted: repr() keeps it on one log line."""
    result = await coordinator.checkout(item_name)
    await _finish(
        coordinator, f"Check-out of {item_name[:_LOG_CHARS]!r}", result, "checked_out"
    )


async def _handle_maintenance_done(
    coordinator: HomeHoardDataUpdateCoordinator, item_id: str, entry_id: str
) -> None:
    """Handle marking maintenance entry as done."""
    result = await coordinator.complete_maintenance(item_id, entry_id)
    what = f"Maintenance entry {entry_id} of item {item_id}"
    await _finish(coordinator, what, result, "done")


async def _handle_reorder(
    coordinator: HomeHoardDataUpdateCoordinator, item_id: str, quantity: str
) -> None:
    """Handle "Bought <quantity> <name>" for a low-stock item.

    The phone has no undo, so a line that worked says what it did to the count.
    """
    result = await coordinator.restocked(item_id, quantity)
    detail = f"bought {result.get('bought', quantity)}"
    if "previousOnHand" in result:
        detail += f", on hand was {result['previousOnHand']}"
    await _finish(coordinator, f"Restock of item {item_id} ({detail})", result, "restocked")
