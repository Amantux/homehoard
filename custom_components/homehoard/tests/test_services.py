"""Home Assistant service behaviour for confidence-tiered item resolution.

These drive REAL `hass.services.async_call`s through the REAL coordinator with
only the HTTP layer mocked, so a regression in either the service schemas or the
coordinator's resolve/checkout logic fails a test. The two that matter most:

  * A low-confidence name must produce `needs_clarification` and write NOTHING.
    Checking out the wrong drill is a silent, physical-world mistake — the whole
    point of the tiering is that an ambiguous name stops the action.
  * `speak_candidates()` must name each option AND where it lives. Spoken aloud,
    "Drill" and "Drill" are indistinguishable; "in Garage" vs "in Workshop" is
    the part that actually lets someone choose.
"""
import os

import yaml
from homeassistant.helpers import aiohttp_client
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homehoard import services
from custom_components.homehoard.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    DOMAIN,
)
from custom_components.homehoard.coordinator import HomeHoardDataUpdateCoordinator

BASE = "http://127.0.0.1:7745"
# One endpoint answers "which item did they mean?" for every caller — the MCP
# server hits it too, so a name resolves identically by voice and by service.
RESOLVE = f"{BASE}/api/v1/resolve"
SERVICES_YAML = os.path.join(os.path.dirname(__file__), "..", "services.yaml")

ITEM = {"id": "i1", "name": "Drill", "where": "Garage"}

# Two things a person would call "drill", told apart only by where they live.
AMBIGUOUS = {
    "confidence": "low",
    "candidates": [
        {"id": "i1", "name": "Drill", "labels": ["power tools"],
         "description": "corded 18V", "where": "Garage", "matchedOn": "name"},
        {"id": "i2", "name": "Drill", "labels": ["cordless"],
         "description": "", "where": "Workshop", "matchedOn": "name"},
    ],
}


async def _setup(hass):
    """Register the services against a real coordinator (HTTP is mocked)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "http://127.0.0.1", CONF_PORT: 7745, CONF_TOKEN: ""},
    )
    entry.add_to_hass(hass)
    session = aiohttp_client.async_get_clientsession(hass)
    coordinator = HomeHoardDataUpdateCoordinator(hass, session, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await services.async_register(hass)
    return coordinator


def _calls(aioclient_mock, method, fragment):
    """Requests made with `method` whose URL contains `fragment`."""
    return [
        c for c in aioclient_mock.mock_calls
        if c[0].lower() == method and fragment in str(c[1])
    ]


# --- registration ---------------------------------------------------------

async def test_every_documented_service_is_registered(hass):
    """services.yaml and the registrations must match 1:1 in both directions.

    An entry with no registration is a service the UI offers but that does
    nothing; a registration with no entry is invisible in Developer Tools.
    """
    await _setup(hass)
    with open(SERVICES_YAML) as fh:
        documented = set(yaml.safe_load(fh))
    registered = set(hass.services.async_services().get(DOMAIN, {}))

    assert documented - registered == set(), "documented but not registered"
    assert registered - documented == set(), "registered but not documented"
    # Guard against the set silently shrinking to nothing.
    assert {"check_out", "check_in", "locate"} <= registered


# --- the voice path reads the options back --------------------------------

def test_speak_candidates_names_each_candidate_and_where_it_lives():
    """The headline behaviour: two identically-named drills are told apart.

    Without the location the question is useless out loud — "I found 2: Drill,
    or Drill" gives the listener nothing to answer with.
    """
    spoken = services.speak_candidates(AMBIGUOUS)

    assert "Garage" in spoken
    assert "Workshop" in spoken
    assert spoken.count("Drill") == 2
    assert spoken.rstrip().endswith("?")   # a question, not an assertion


def test_speak_candidates_handles_a_single_option():
    single = {"candidates": [AMBIGUOUS["candidates"][0]]}
    assert services.speak_candidates(single) == "Did you mean Drill in Garage?"


def test_speak_action_routes_a_clarification_to_the_question():
    """needs_clarification must reach speak_candidates, not the error fallback.

    Before the tiering existed this status fell through to "Sorry, something
    went wrong" — technically true, and completely unhelpful.
    """
    spoken = services.speak_action({"status": "needs_clarification", **AMBIGUOUS})

    assert "Garage" in spoken and "Workshop" in spoken
    assert "something went wrong" not in spoken


# --- a low-confidence name must not act -----------------------------------

async def test_check_out_low_confidence_returns_candidates_and_writes_nothing(
    hass, aioclient_mock
):
    """An ambiguous name stops the check-out. Nothing is guessed at."""
    aioclient_mock.get(RESOLVE, json=AMBIGUOUS)
    # Mocked so a regression that DOES act succeeds at the HTTP layer and is
    # caught by the call-count assertion below, not by a confusing 404.
    aioclient_mock.post(f"{BASE}/api/v1/items/i1/checkout", json={})
    await _setup(hass)

    result = await hass.services.async_call(
        DOMAIN, "check_out", {"name": "drill"},
        blocking=True, return_response=True,
    )

    assert result["status"] == "needs_clarification"
    assert len(result["candidates"]) == 2
    # The reply a person actually hears names both places.
    assert "Garage" in result["speech"] and "Workshop" in result["speech"]
    assert _calls(aioclient_mock, "post", "/checkout") == []


async def test_check_in_low_confidence_writes_nothing(hass, aioclient_mock):
    """Same guard on the way back in — symmetry matters, one is not enough."""
    aioclient_mock.get(RESOLVE, json=AMBIGUOUS)
    aioclient_mock.post(f"{BASE}/api/v1/items/i1/checkin", json={})
    await _setup(hass)

    result = await hass.services.async_call(
        DOMAIN, "check_in", {"name": "drill"},
        blocking=True, return_response=True,
    )

    assert result["status"] == "needs_clarification"
    assert _calls(aioclient_mock, "post", "/checkin") == []


# --- a confident name still acts ------------------------------------------

async def test_check_out_high_confidence_checks_the_item_out(hass, aioclient_mock):
    """The tiering must not make the common case harder: one match still acts."""
    aioclient_mock.get(RESOLVE, json={"confidence": "high", "match": ITEM})
    aioclient_mock.post(f"{BASE}/api/v1/items/i1/checkout", json={})
    await _setup(hass)

    result = await hass.services.async_call(
        DOMAIN, "check_out", {"name": "Drill"},
        blocking=True, return_response=True,
    )

    assert result["status"] == "checked_out"
    assert result["name"] == "Drill"
    assert len(_calls(aioclient_mock, "post", "/checkout")) == 1
    assert "checked out" in result["speech"].lower()


async def test_an_unknown_name_is_reported_not_guessed(hass, aioclient_mock):
    aioclient_mock.get(RESOLVE, json={"confidence": "none", "candidates": []})
    aioclient_mock.post(f"{BASE}/api/v1/items/i1/checkout", json={})
    await _setup(hass)

    result = await hass.services.async_call(
        DOMAIN, "check_out", {"name": "sonic screwdriver"},
        blocking=True, return_response=True,
    )

    assert result["status"] == "not_found"
    assert _calls(aioclient_mock, "post", "/checkout") == []
