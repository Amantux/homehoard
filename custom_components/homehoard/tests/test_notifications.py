"""Actionable notifications, driven through the real event bus.

Everything above the HTTP layer is real: a config entry set up the way Home
Assistant does it, the listener it registers, the coordinator it calls. Each test
asserts the requests that came out (method, URL, payload), or that none did.

One trap shapes these tests. The HTTP mock raises on a request nobody registered,
and that exception dies inside the handler's background task, so "no write was
recorded" proves nothing unless the write would have been recorded. Tests that
assert an absence therefore register a catch-all first (_catch_all_writes).
"""
import re
from unittest.mock import patch

import pytest
from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homehoard import notifications
from custom_components.homehoard.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    DOMAIN,
)

BASE = "http://127.0.0.1:7745"
SUMMARY = f"{BASE}/api/v1/ha/summary"
RESOLVE = f"{BASE}/api/v1/resolve"
RESTOCKED = f"{BASE}/api/v1/restock/i1/restocked"
MAINTENANCE = f"{BASE}/api/v1/items/i9/maintenance/e1"
EVENT = "mobile_app_notification_action"

AMBIGUOUS = {
    "confidence": "low",
    "candidates": [
        {"id": "i1", "name": "Drill", "where": "Garage"},
        {"id": "i2", "name": "Drill", "where": "Workshop"},
    ],
}


def _summary(restock=()):
    return {
        "health": True,
        "restock": {"count": len(restock), "items": list(restock)},
        "maintenance": {"overdue": 0, "upcoming30": 0, "entries": []},
        "totals": {},
    }


async def _load_entry(hass, aioclient_mock, host="http://127.0.0.1", token="", summary=None):
    """Set up an entry the way Home Assistant does (HTTP is mocked)."""
    aioclient_mock.get(f"{host}:7745/api/v1/ha/summary", json=summary or _summary())
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: host, CONF_PORT: 7745, CONF_TOKEN: token}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture(autouse=True)
async def _unload_entries(hass):
    """Unload what a test left loaded: a refresh leaves a cooldown timer running."""
    yield
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)


async def _tap(hass, action):
    hass.bus.async_fire(EVENT, {"action": action})
    await hass.async_block_till_done()


def _catch_all_writes(aioclient_mock):
    """Make any write succeed and get recorded, so a stray one fails the test."""
    aioclient_mock.post(re.compile(".*"), json={})
    aioclient_mock.put(re.compile(".*"), json={})


def _writes(aioclient_mock):
    return [
        (c[0].lower(), str(c[1]), c[2])
        for c in aioclient_mock.mock_calls
        if c[0].lower() != "get"
    ]


def _summary_polls(aioclient_mock):
    return sum(
        1 for c in aioclient_mock.mock_calls
        if c[0].lower() == "get" and str(c[1]).endswith("/api/v1/ha/summary")
    )


def _listeners(hass):
    return hass.bus.async_listeners().get(EVENT, 0)


# --- parsing ----------------------------------------------------------------

def test_parse_checkin_action():
    assert notifications._parse_checkin_action("hoard:checkin:Drill") == "Drill"
    assert notifications._parse_checkin_action("hoard:checkin:Power Drill") == "Power Drill"
    assert notifications._parse_checkin_action("hoard:checkout:Drill") is None
    assert notifications._parse_checkin_action("random:checkin:Drill") is None


def test_parse_checkout_action():
    assert notifications._parse_checkout_action("hoard:checkout:Drill") == "Drill"
    assert notifications._parse_checkout_action("hoard:checkout:Power Drill") == "Power Drill"
    assert notifications._parse_checkout_action("hoard:checkin:Drill") is None
    assert notifications._parse_checkout_action("random:checkout:Drill") is None


def test_parse_maintenance_done_action():
    parse = notifications._parse_maintenance_done_action
    assert parse("hoard:maintenance_done:i123:e456") == ("i123", "e456")
    assert parse("hoard:checkin:i123") is None
    assert parse("hoard:maintenance_done:i123") is None
    assert parse("hoard:maintenance_done:i123:e456:extra") is None
    assert parse("hoard:maintenance_done::e456") is None


def test_parse_reorder_action():
    parse = notifications._parse_reorder_action
    assert parse("hoard:restock:i123:3") == ("i123", "3")
    assert parse("hoard:restock:i123:2.625") == ("i123", "2.625")
    assert parse("hoard:restock:3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b:999999999.999") == (
        "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b", "999999999.999"
    )
    assert parse("hoard:checkin:i123:3") is None
    assert parse("random:restock:i123:3") is None
    assert parse("hoard:restock:") is None
    # No amount, no tap: what the server suggests by now isn't what was bought.
    assert parse("hoard:restock:i123") is None


# --- each action, by what it sends ------------------------------------------

async def test_restock_tap_posts_the_amount_it_carries_and_refreshes(hass, aioclient_mock):
    aioclient_mock.post(RESTOCKED, json={"id": "i1"})
    await _load_entry(hass, aioclient_mock)
    polls = _summary_polls(aioclient_mock)

    await _tap(hass, "hoard:restock:i1:3")

    assert _writes(aioclient_mock) == [("post", RESTOCKED, {"quantity": 3})]
    assert _summary_polls(aioclient_mock) == polls + 1


async def test_a_restock_tap_logs_what_it_did_to_the_count(hass, aioclient_mock, caplog):
    """The phone has no undo, so this line is what a mistaken tap is put right from."""
    caplog.set_level("INFO", logger="custom_components.homehoard.notifications")
    aioclient_mock.post(RESTOCKED, json={"bought": 3, "previousOnHand": 0, "onHand": 3})
    await _load_entry(hass, aioclient_mock)

    await _tap(hass, "hoard:restock:i1:3")

    assert "Restock of item i1 (bought 3, on hand was 0): restocked" in caplog.text


async def test_maintenance_tap_puts_the_households_date(hass, aioclient_mock, freezer):
    """A PUT, because POST on this route is a 405, and a real date, because the
    backend parses "now" to None and would quietly leave the entry not done.

    The frozen instant is already Mar 2 in UTC but still Mar 1 in the test zone
    (US/Pacific). The app stores completion as a calendar date and counts the next
    occurrence from it, so the household's day is the one that has to arrive.
    """
    freezer.move_to("2026-03-02 03:00:00+00:00")
    aioclient_mock.put(MAINTENANCE, json={"id": "e1"})
    await _load_entry(hass, aioclient_mock)
    polls = _summary_polls(aioclient_mock)

    await _tap(hass, "hoard:maintenance_done:i9:e1")

    assert _writes(aioclient_mock) == [
        ("put", MAINTENANCE, {"completedDate": "2026-03-01", "onlyIfOpen": True})
    ]
    assert _summary_polls(aioclient_mock) == polls + 1


@pytest.mark.parametrize(
    ("verb", "done_word"), [("checkin", "checked_in"), ("checkout", "checked_out")]
)
async def test_name_tap_resolves_then_writes_the_resolved_id(
    hass, aioclient_mock, caplog, verb, done_word
):
    """The name goes to the resolver as a query; only the id it returns is written."""
    caplog.set_level("INFO", logger="custom_components.homehoard.notifications")
    aioclient_mock.get(RESOLVE, json={"confidence": "high", "match": {"id": "i1", "name": "Drill"}})
    aioclient_mock.post(f"{BASE}/api/v1/items/i1/{verb}", json={})
    await _load_entry(hass, aioclient_mock)
    polls = _summary_polls(aioclient_mock)

    await _tap(hass, f"hoard:{verb}:Power Drill")

    resolves = [c for c in aioclient_mock.mock_calls if "/resolve" in str(c[1])]
    assert len(resolves) == 1
    assert resolves[0][1].query["q"] == "Power Drill"
    assert _writes(aioclient_mock) == [("post", f"{BASE}/api/v1/items/i1/{verb}", {})]
    assert _summary_polls(aioclient_mock) == polls + 1
    assert done_word in caplog.text


async def test_actions_carry_the_integrations_token(hass, aioclient_mock):
    aioclient_mock.post(RESTOCKED, json={})
    aioclient_mock.put(MAINTENANCE, json={})
    await _load_entry(hass, aioclient_mock, token="secret-token")

    await _tap(hass, "hoard:restock:i1:3")
    await _tap(hass, "hoard:maintenance_done:i9:e1")

    writes = [c for c in aioclient_mock.mock_calls if c[0].lower() != "get"]
    assert len(writes) == 2
    assert all(c[3]["Authorization"] == "Bearer secret-token" for c in writes)


async def test_a_tap_updates_the_sensor_and_the_to_do_list(hass, aioclient_mock):
    low = {"id": "i1", "name": "AA batteries", "onHand": 1, "suggestedQuantity": 11, "oneTap": True}
    await _load_entry(hass, aioclient_mock, summary=_summary([low]))
    assert hass.states.get("sensor.homehoard_restock_needed").state == "1"
    assert hass.states.get("todo.homehoard_restock_list").state == "1"

    # From here on the server says the item is no longer low.
    aioclient_mock.clear_requests()
    aioclient_mock.post(RESTOCKED, json={})
    aioclient_mock.get(SUMMARY, json=_summary())
    await _tap(hass, "hoard:restock:i1:11")

    assert hass.states.get("sensor.homehoard_restock_needed").state == "0"
    assert hass.states.get("todo.homehoard_restock_list").state == "0"


# --- outcomes stay distinguishable ------------------------------------------

@pytest.mark.parametrize(
    ("http_status", "outcome"),
    [
        (200, "restocked"),
        (404, "not_found"),
        (409, "several_placements"),
        (422, "not_low"),
        (401, "error"),
        (500, "error"),
    ],
)
async def test_restocked_names_each_answer(hass, aioclient_mock, http_status, outcome):
    aioclient_mock.post(RESTOCKED, status=http_status, json={})
    entry = await _load_entry(hass, aioclient_mock)

    result = await hass.data[DOMAIN][entry.entry_id].restocked("i1", "3")

    assert result == {"status": outcome}


@pytest.mark.parametrize(
    ("http_status", "outcome"),
    [(200, "done"), (404, "not_found"), (409, "no_longer_open"), (500, "error")],
)
async def test_complete_maintenance_names_each_answer(hass, aioclient_mock, http_status, outcome):
    aioclient_mock.put(MAINTENANCE, status=http_status, json={})
    entry = await _load_entry(hass, aioclient_mock)

    result = await hass.data[DOMAIN][entry.entry_id].complete_maintenance("i9", "e1")

    assert result == {"status": outcome}


@pytest.mark.parametrize(
    ("http_status", "outcome"),
    [(409, "several_placements"), (422, "not_low"), (404, "not_found"), (500, "error")],
)
async def test_a_refused_tap_is_logged_and_changes_nothing(
    hass, aioclient_mock, caplog, http_status, outcome
):
    """A stale button (restocked since, kept in several places) is an outcome, not a crash."""
    aioclient_mock.post(RESTOCKED, status=http_status, json={"error": "nope"})
    await _load_entry(hass, aioclient_mock)
    polls = _summary_polls(aioclient_mock)

    await _tap(hass, "hoard:restock:i1:3")

    assert f"Restock of item i1 (bought 3): {outcome}" in caplog.text
    assert _summary_polls(aioclient_mock) == polls, "refreshed although nothing changed"


async def test_a_done_tap_on_an_entry_no_longer_open_is_logged_and_changes_nothing(
    hass, aioclient_mock, caplog
):
    """Already done in the app, or on another phone: the server keeps the real date."""
    aioclient_mock.put(MAINTENANCE, status=409, json={"error": "nope"})
    await _load_entry(hass, aioclient_mock)
    polls = _summary_polls(aioclient_mock)

    await _tap(hass, "hoard:maintenance_done:i9:e1")

    assert "Maintenance entry e1 of item i9: no_longer_open" in caplog.text
    assert _summary_polls(aioclient_mock) == polls, "refreshed although nothing changed"


@pytest.mark.parametrize("error", [ClientError("boom"), TimeoutError()])
@pytest.mark.parametrize(
    ("action", "method", "url"),
    [
        ("hoard:restock:i1:3", "post", RESTOCKED),
        ("hoard:maintenance_done:i9:e1", "put", MAINTENANCE),
    ],
)
async def test_an_unreachable_server_is_logged_not_raised(
    hass, aioclient_mock, caplog, error, action, method, url
):
    aioclient_mock.request(method, url, exc=error)
    await _load_entry(hass, aioclient_mock)
    polls = _summary_polls(aioclient_mock)

    await _tap(hass, action)

    assert "got no answer" in caplog.text
    assert ": error" in caplog.text
    assert _summary_polls(aioclient_mock) == polls


@pytest.mark.parametrize(
    ("write", "url"),
    [
        (lambda c: c.restocked("i1", "3"), RESTOCKED),
        (lambda c: c.complete_maintenance("i9", "e1"), MAINTENANCE),
    ],
)
async def test_a_write_cannot_wait_forever(hass, aioclient_mock, write, url):
    """Nobody is watching a tap, so a server that never answers must not hold it open."""
    aioclient_mock.post(RESTOCKED, json={})
    aioclient_mock.put(MAINTENANCE, json={})
    entry = await _load_entry(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    with patch.object(
        coordinator._session, "request", wraps=coordinator._session.request
    ) as request:
        await write(coordinator)

    assert request.call_args.kwargs["timeout"].total == 10
    assert request.call_args.args[1] == url


# --- lifecycle: one tap is one call, and unload really unloads --------------

async def test_unloading_the_last_entry_succeeds_and_stops_listening(hass, aioclient_mock):
    """This was the crash: EventBus has no async_listen_remove, so the unload blew up."""
    _catch_all_writes(aioclient_mock)
    entry = await _load_entry(hass, aioclient_mock)
    assert _listeners(hass) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert _listeners(hass) == 0
    await _tap(hass, "hoard:restock:i1:3")
    assert _writes(aioclient_mock) == []


async def test_after_a_reload_one_tap_is_one_call(hass, aioclient_mock):
    _catch_all_writes(aioclient_mock)
    entry = await _load_entry(hass, aioclient_mock)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    await _tap(hass, "hoard:restock:i1:3")
    assert _writes(aioclient_mock) == [("post", RESTOCKED, {"quantity": 3})]


async def test_a_second_entry_does_not_add_a_second_listener(hass, aioclient_mock):
    """The guard's own test: with one entry, unload-on-reload hides a missing guard."""
    _catch_all_writes(aioclient_mock)
    first = await _load_entry(hass, aioclient_mock)
    second = await _load_entry(hass, aioclient_mock, host="http://127.0.0.2")
    assert _listeners(hass) == 1

    await _tap(hass, "hoard:restock:i1:3")
    assert len(_writes(aioclient_mock)) == 1, "one tap acted more than once"

    # Reloading one while the other stays up must not stack a listener either.
    assert await hass.config_entries.async_reload(second.entry_id)
    await hass.async_block_till_done()
    assert _listeners(hass) == 1

    # Unloading one keeps the feature working for the other...
    assert await hass.config_entries.async_unload(first.entry_id)
    assert _listeners(hass) == 1
    aioclient_mock.clear_requests()
    _catch_all_writes(aioclient_mock)
    aioclient_mock.get(re.compile("/api/v1/ha/summary"), json=_summary())
    await _tap(hass, "hoard:restock:i1:3")
    assert len(_writes(aioclient_mock)) == 1

    # ...and only the last one takes it down.
    assert await hass.config_entries.async_unload(second.entry_id)
    assert _listeners(hass) == 0


# --- what must not act ------------------------------------------------------

@pytest.mark.parametrize(
    "data",
    [
        {"action": "unknown:action"},
        {"action": "URI"},
        {"action": 123},
        {"no_action_field": True},
    ],
)
async def test_other_peoples_notifications_are_ignored_quietly(
    hass, aioclient_mock, caplog, data
):
    """Every Companion app notification in the house arrives on this event."""
    _catch_all_writes(aioclient_mock)
    aioclient_mock.get(re.compile("/api/v1/(resolve|items)"), json={})
    await _load_entry(hass, aioclient_mock)
    calls_before = len(aioclient_mock.mock_calls)
    caplog.clear()

    hass.bus.async_fire(EVENT, data)
    await hass.async_block_till_done()

    assert len(aioclient_mock.mock_calls) == calls_before
    assert caplog.text == ""


@pytest.mark.parametrize(
    "action",
    [
        "hoard:restock:",
        "hoard:restock",
        "hoard:restock:i1",
        "hoard:restock:i1:",
        "hoard:restock::3",
        "hoard:restock:i1:3:extra",
        "hoard:restock:i1:abc",
        "hoard:restock:i1:-1",
        "hoard:restock:i1:+1",
        "hoard:restock:i1:1e5",
        "hoard:restock:i1:NaN",
        "hoard:restock:i1:Infinity",
        "hoard:restock:i1:.5",
        "hoard:restock:i1:1.",
        "hoard:restock:i1:1.2345",
        "hoard:restock:i1:1234567890",
        "hoard:restock:i1:٣",
        "hoard:restock:i1:3\n",
        "hoard:maintenance_done:i9",
        "hoard:maintenance_done:i9:e1:extra",
        "hoard:checkin:",
        "hoard:checkout:",
        "hoard:unknown:i1",
    ],
)
async def test_a_malformed_hoard_action_makes_no_request(hass, aioclient_mock, caplog, action):
    _catch_all_writes(aioclient_mock)
    aioclient_mock.get(re.compile("/api/v1/(resolve|items)"), json={})
    await _load_entry(hass, aioclient_mock)
    calls_before = len(aioclient_mock.mock_calls)

    await _tap(hass, action)

    assert len(aioclient_mock.mock_calls) == calls_before
    assert "Ignoring unknown HomeHoard action" in caplog.text


async def test_a_tap_with_no_server_set_up_is_logged(hass, aioclient_mock, caplog):
    _catch_all_writes(aioclient_mock)
    notifications.async_setup(hass)

    await _tap(hass, "hoard:restock:i1:3")

    assert "HomeHoard is not set up" in caplog.text
    assert _writes(aioclient_mock) == []
    notifications.async_unload(hass)


# --- security: the action string is attacker-controlled ---------------------

@pytest.mark.parametrize(
    "action",
    [
        # Resolves to POST /api/v1/tokens: dot segments collapse, "?" eats the rest.
        # Every one carries a valid amount, so only the id check can stop it.
        "hoard:restock:../../v1/tokens?x=:3",
        "hoard:restock:..:3",
        "hoard:restock:a/b:3",
        "hoard:restock:a?b=c:3",
        "hoard:restock:a#b:3",
        "hoard:restock:a%2Fb:3",
        "hoard:restock:a b:3",
        "hoard:restock:i1\n:3",
        f"hoard:restock:{'a' * 65}:3",
        "hoard:maintenance_done:../../v1/users:e1",
        "hoard:maintenance_done:i9:../../../v1/tokens?x=",
        "hoard:maintenance_done:i9\n:e1",
    ],
)
async def test_a_crafted_id_never_reaches_a_url(hass, aioclient_mock, action):
    """Non-admin users can fire this event (mobile_app webhook) and it runs with our token."""
    _catch_all_writes(aioclient_mock)
    await _load_entry(hass, aioclient_mock)

    await _tap(hass, action)

    assert _writes(aioclient_mock) == []


@pytest.mark.parametrize("verb", ["checkin", "checkout"])
@pytest.mark.parametrize(
    ("resolved", "outcome"),
    [(AMBIGUOUS, "needs_clarification"), ({"confidence": "none"}, "not_found")],
)
async def test_a_name_the_resolver_wont_commit_to_writes_nothing(
    hass, aioclient_mock, caplog, verb, resolved, outcome
):
    """Ambiguity refuses: the tiered resolver is asked, and its "no" stops the write."""
    aioclient_mock.get(RESOLVE, json=resolved)
    _catch_all_writes(aioclient_mock)
    await _load_entry(hass, aioclient_mock)

    await _tap(hass, f"hoard:{verb}:drill")

    resolves = [c for c in aioclient_mock.mock_calls if "/resolve" in str(c[1])]
    assert [c[1].query["q"] for c in resolves] == ["drill"]
    assert _writes(aioclient_mock) == []
    assert outcome in caplog.text


async def test_a_name_cannot_forge_a_log_line(hass, aioclient_mock, caplog):
    aioclient_mock.get(RESOLVE, json={"confidence": "none"})
    await _load_entry(hass, aioclient_mock)

    await _tap(hass, "hoard:checkin:Drill\nERROR forged entry")

    assert "Check-in of" in caplog.text
    assert "\nERROR forged entry" not in caplog.text


@pytest.mark.parametrize("action", ["hoard:checkin:", "hoard:restock:", "hoard:unknown:"])
async def test_a_huge_action_cannot_flood_the_log(hass, aioclient_mock, caplog, action):
    aioclient_mock.get(RESOLVE, json={"confidence": "none"})
    await _load_entry(hass, aioclient_mock)

    await _tap(hass, action + "x" * 100_000)

    assert "HomeHoard" in caplog.text or "Check-in of" in caplog.text
    assert "x" * 200 not in caplog.text
