"""Voice intent + response service so you can ask 'where is my drill?'.

Both the Assist intent and the ``homehoard.locate`` service (usable from
automations / notifications / messaging) call the HomeHoard search API and share
the same phrasing.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv, intent

from .const import (
    DOMAIN,
    INTENT_CHECKIN,
    INTENT_CHECKOUT,
    INTENT_CONTENTS,
    INTENT_LOCATE,
    SERVICE_CHECKIN,
    SERVICE_CHECKOUT,
    SERVICE_CONTENTS,
    SERVICE_LOCATE,
)

_REGISTERED = f"{DOMAIN}_services_registered"


def _first_coordinator(hass: HomeAssistant):
    for value in hass.data.get(DOMAIN, {}).values():
        if hasattr(value, "search"):
            return value
    return None


def speak(query: str, results: list[dict]) -> str:
    """Turn search results into a spoken/notification sentence."""
    if not results:
        return f"I couldn't find {query} in your inventory."

    r = results[0]
    name = r.get("name", query)
    where = r.get("where") or ""
    count = r.get("count", 0)

    if r["type"] == "item":
        if not where or where == "Unassigned":
            sentence = f"{name} isn't assigned to a location yet."
        else:
            sentence = f"{name} is in {where}."
    elif r["type"] == "bin":
        loc = f" in {where}" if where else ""
        sentence = f"{name} is a bin{loc} containing {count} item" \
                   f"{'' if count == 1 else 's'}."
    else:  # location
        sentence = f"{name} is a location with {count} item" \
                   f"{'' if count == 1 else 's'} directly inside."

    if len(results) > 1:
        sentence += f" I found {len(results)} matches in total."
    return sentence


def speak_action(status: dict) -> str:
    """Turn a coordinator check-out/in result into a spoken sentence."""
    name = status.get("name", "that")
    return {
        "checked_out": f"Okay, I've checked out {name}.",
        "already_out": f"{name} is already checked out.",
        "checked_in": f"Okay, {name} is back in.",
        "already_in": f"{name} is already here.",
        "not_found": f"I couldn't find {name} in your inventory.",
    }.get(status.get("status"), f"Sorry, something went wrong with {name}.")


def speak_contents(status: dict) -> str:
    """Turn a coordinator contents() result into a spoken sentence."""
    name = status.get("name", "that")
    if status.get("status") == "not_found":
        return f"I couldn't find {name} in your inventory."
    if status.get("status") != "ok":
        return f"Sorry, I couldn't read what's in {name}."
    items = [i for i in status.get("items", []) if i]
    bins = [b for b in status.get("bins", []) if b]
    if not items and not bins:
        return f"{name} is empty."
    parts = []
    if items:
        shown = ", ".join(items[:8])
        more = f", and {len(items) - 8} more" if len(items) > 8 else ""
        parts.append(f"{len(items)} item{'' if len(items) == 1 else 's'}: {shown}{more}")
    if bins:
        parts.append(f"{len(bins)} bin{'' if len(bins) == 1 else 's'}: {', '.join(bins[:6])}")
    return f"{name} contains " + "; ".join(parts) + "."


class LocateIntentHandler(intent.IntentHandler):
    """Handles 'where is my <name>' style requests."""

    intent_type = INTENT_LOCATE
    slot_schema = {vol.Required("name"): cv.string}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        name = intent_obj.slots["name"]["value"]
        response = intent_obj.create_response()
        coordinator = _first_coordinator(hass)
        if coordinator is None:
            response.async_set_speech("HomeHoard isn't set up yet.")
            return response
        results = await coordinator.search(name)
        response.async_set_speech(speak(name, results))
        return response


class _ActionIntentHandler(intent.IntentHandler):
    """Shared base for the check-out / check-in voice intents."""

    slot_schema = {vol.Required("name"): cv.string}
    _method = ""  # "checkout" | "checkin"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        name = intent_obj.slots["name"]["value"]
        response = intent_obj.create_response()
        coordinator = _first_coordinator(hass)
        if coordinator is None:
            response.async_set_speech("HomeHoard isn't set up yet.")
            return response
        status = await getattr(coordinator, self._method)(name)
        response.async_set_speech(speak_action(status))
        return response


class CheckOutIntentHandler(_ActionIntentHandler):
    intent_type = INTENT_CHECKOUT
    _method = "checkout"


class CheckInIntentHandler(_ActionIntentHandler):
    intent_type = INTENT_CHECKIN
    _method = "checkin"


class ContentsIntentHandler(intent.IntentHandler):
    """Handles 'what's in the garage / bin 3' style requests."""

    intent_type = INTENT_CONTENTS
    slot_schema = {vol.Required("name"): cv.string}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        name = intent_obj.slots["name"]["value"]
        response = intent_obj.create_response()
        coordinator = _first_coordinator(hass)
        if coordinator is None:
            response.async_set_speech("HomeHoard isn't set up yet.")
            return response
        status = await coordinator.contents(name)
        response.async_set_speech(speak_contents(status))
        return response


async def async_register(hass: HomeAssistant) -> None:
    if hass.data.get(_REGISTERED):
        return
    hass.data[_REGISTERED] = True

    intent.async_register(hass, LocateIntentHandler())
    intent.async_register(hass, CheckOutIntentHandler())
    intent.async_register(hass, CheckInIntentHandler())
    intent.async_register(hass, ContentsIntentHandler())

    async def _handle_locate(call: ServiceCall) -> dict:
        query = call.data["query"]
        coordinator = _first_coordinator(hass)
        results = await coordinator.search(query) if coordinator else []
        return {"results": results, "speech": speak(query, results)}

    hass.services.async_register(
        DOMAIN,
        SERVICE_LOCATE,
        _handle_locate,
        schema=vol.Schema({vol.Required("query"): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )

    def _action_service(method: str):
        async def _handle(call: ServiceCall) -> dict:
            coordinator = _first_coordinator(hass)
            if coordinator is None:
                return {"status": "error", "speech": "HomeHoard isn't set up yet."}
            status = await getattr(coordinator, method)(call.data["name"])
            return {**status, "speech": speak_action(status)}

        return _handle

    for service, method in ((SERVICE_CHECKOUT, "checkout"), (SERVICE_CHECKIN, "checkin")):
        hass.services.async_register(
            DOMAIN,
            service,
            _action_service(method),
            schema=vol.Schema({vol.Required("name"): cv.string}),
            supports_response=SupportsResponse.OPTIONAL,
        )

    async def _handle_contents(call: ServiceCall) -> dict:
        coordinator = _first_coordinator(hass)
        status = await coordinator.contents(call.data["query"]) if coordinator else {}
        return {**status, "speech": speak_contents(status)}

    hass.services.async_register(
        DOMAIN,
        SERVICE_CONTENTS,
        _handle_contents,
        schema=vol.Schema({vol.Required("query"): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )


def async_unregister(hass: HomeAssistant) -> None:
    for service in (SERVICE_LOCATE, SERVICE_CHECKOUT, SERVICE_CHECKIN, SERVICE_CONTENTS):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
    hass.data.pop(_REGISTERED, None)
