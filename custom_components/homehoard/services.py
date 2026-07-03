"""Voice intent + response service so you can ask 'where is my drill?'.

Both the Assist intent and the ``homehoard.locate`` service (usable from
automations / notifications / messaging) call the HomeHoard search API and share
the same phrasing.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv, intent

from .const import DOMAIN, INTENT_LOCATE, SERVICE_LOCATE

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


async def async_register(hass: HomeAssistant) -> None:
    if hass.data.get(_REGISTERED):
        return
    hass.data[_REGISTERED] = True

    intent.async_register(hass, LocateIntentHandler())

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


def async_unregister(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_LOCATE):
        hass.services.async_remove(DOMAIN, SERVICE_LOCATE)
    hass.data.pop(_REGISTERED, None)
