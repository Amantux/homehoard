"""Tests for HomeHoard actionable notifications.

These tests verify that mobile_app_notification_action events are correctly
mapped to coordinator methods and that the notification action parsing works.
"""

from custom_components.homehoard import notifications
from custom_components.homehoard.const import DOMAIN


# --- Action parsing tests ---------------------------------------------------

def test_parse_checkin_action():
    """Test parsing check-in action payloads."""
    assert notifications._parse_checkin_action("hoard:checkin:Drill") == "Drill"
    assert notifications._parse_checkin_action("hoard:checkin:Power Drill") == "Power Drill"
    assert notifications._parse_checkin_action("hoard:checkout:Drill") is None
    assert notifications._parse_checkin_action("random:checkin:Drill") is None


def test_parse_checkout_action():
    """Test parsing check-out action payloads."""
    assert notifications._parse_checkout_action("hoard:checkout:Drill") == "Drill"
    assert notifications._parse_checkout_action("hoard:checkout:Power Drill") == "Power Drill"
    assert notifications._parse_checkout_action("hoard:checkin:Drill") is None
    assert notifications._parse_checkout_action("random:checkout:Drill") is None


def test_parse_maintenance_done_action():
    """Test parsing maintenance done action payloads."""
    result = notifications._parse_maintenance_done_action("hoard:maintenance_done:i123:e456")
    assert result == ("i123", "e456")

    result = notifications._parse_maintenance_done_action("hoard:maintenance_done:i1:e2")
    assert result == ("i1", "e2")

    assert notifications._parse_maintenance_done_action("hoard:checkin:i123") is None
    assert notifications._parse_maintenance_done_action("hoard:maintenance_done:i123") is None
    assert notifications._parse_maintenance_done_action("hoard:maintenance_done:i123:e456:extra") is None


def test_parse_reorder_action():
    """Test parsing reorder action payloads."""
    assert notifications._parse_reorder_action("hoard:restock:i123") == "i123"
    assert notifications._parse_reorder_action("hoard:restock:i1") == "i1"
    assert notifications._parse_reorder_action("hoard:checkin:i123") is None
    assert notifications._parse_reorder_action("random:restock:i123") is None


# --- Notification handler tests ---------------------------------------------

async def test_checkin_action_calls_coordinator(hass, aioclient_mock):
    """Test that check-in actions trigger the coordinator's checkin method."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import aiohttp_client

    # Setup coordinator
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "http://127.0.0.1", "port": 7745, "token": ""},
    )
    entry.add_to_hass(hass)
    session = aiohttp_client.async_get_clientsession(hass)
    from custom_components.homehoard.coordinator import HomeHoardDataUpdateCoordinator
    coordinator = HomeHoardDataUpdateCoordinator(hass, session, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Setup notifications listener
    notifications.async_setup(hass)

    # Mock the checkin response
    aioclient_mock.get("http://127.0.0.1:7745/api/v1/resolve", json={
        "confidence": "high",
        "match": {"id": "i1", "name": "Drill"}
    })
    aioclient_mock.post("http://127.0.0.1:7745/api/v1/items/i1/checkin", json={
        "status": "checked_in"
    })

    # Fire the notification action event
    hass.bus.async_fire("mobile_app_notification_action", {
        "action": "hoard:checkin:Drill"
    })
    await hass.async_block_till_done()


async def test_checkout_action_calls_coordinator(hass, aioclient_mock):
    """Test that check-out actions trigger the coordinator's checkout method."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import aiohttp_client

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "http://127.0.0.1", "port": 7745, "token": ""},
    )
    entry.add_to_hass(hass)
    session = aiohttp_client.async_get_clientsession(hass)
    from custom_components.homehoard.coordinator import HomeHoardDataUpdateCoordinator
    coordinator = HomeHoardDataUpdateCoordinator(hass, session, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    notifications.async_setup(hass)

    aioclient_mock.get("http://127.0.0.1:7745/api/v1/resolve", json={
        "confidence": "high",
        "match": {"id": "i1", "name": "Drill"}
    })
    aioclient_mock.post("http://127.0.0.1:7745/api/v1/items/i1/checkout", json={
        "status": "checked_out"
    })

    hass.bus.async_fire("mobile_app_notification_action", {
        "action": "hoard:checkout:Drill"
    })
    await hass.async_block_till_done()


async def test_maintenance_done_action_calls_coordinator(hass, aioclient_mock):
    """Test that maintenance done actions trigger the coordinator's API call."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import aiohttp_client

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "http://127.0.0.1", "port": 7745, "token": ""},
    )
    entry.add_to_hass(hass)
    session = aiohttp_client.async_get_clientsession(hass)
    from custom_components.homehoard.coordinator import HomeHoardDataUpdateCoordinator
    coordinator = HomeHoardDataUpdateCoordinator(hass, session, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    notifications.async_setup(hass)

    # Mock the maintenance completion endpoint
    aioclient_mock.post("http://127.0.0.1:7745/api/v1/items/i123/maintenance/e456", json={
        "id": "e456",
        "completedDate": "2026-10-22T00:00:00+00:00"
    })

    hass.bus.async_fire("mobile_app_notification_action", {
        "action": "hoard:maintenance_done:i123:e456"
    })
    await hass.async_block_till_done()


async def test_reorder_action_calls_coordinator(hass, aioclient_mock):
    """Test that reorder actions trigger the coordinator's API call."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import aiohttp_client

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "http://127.0.0.1", "port": 7745, "token": ""},
    )
    entry.add_to_hass(hass)
    session = aiohttp_client.async_get_clientsession(hass)
    from custom_components.homehoard.coordinator import HomeHoardDataUpdateCoordinator
    coordinator = HomeHoardDataUpdateCoordinator(hass, session, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    notifications.async_setup(hass)

    # Mock the item lookup
    aioclient_mock.get("http://127.0.0.1:7745/api/v1/items/i123", json={
        "id": "i123",
        "name": "Drill"
    })

    hass.bus.async_fire("mobile_app_notification_action", {
        "action": "hoard:restock:i123"
    })
    await hass.async_block_till_done()


async def test_unknown_action_is_ignored(hass, aioclient_mock):
    """Test that unknown action types are safely ignored."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import aiohttp_client

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "http://127.0.0.1", "port": 7745, "token": ""},
    )
    entry.add_to_hass(hass)
    session = aiohttp_client.async_get_clientsession(hass)
    from custom_components.homehoard.coordinator import HomeHoardDataUpdateCoordinator
    coordinator = HomeHoardDataUpdateCoordinator(hass, session, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    notifications.async_setup(hass)

    # No mock calls expected for unknown action
    hass.bus.async_fire("mobile_app_notification_action", {
        "action": "unknown:action"
    })
    await hass.async_block_till_done()


async def test_missing_action_is_ignored(hass, aioclient_mock):
    """Test that events without an action field are safely ignored."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import aiohttp_client

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "http://127.0.0.1", "port": 7745, "token": ""},
    )
    entry.add_to_hass(hass)
    session = aiohttp_client.async_get_clientsession(hass)
    from custom_components.homehoard.coordinator import HomeHoardDataUpdateCoordinator
    coordinator = HomeHoardDataUpdateCoordinator(hass, session, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    notifications.async_setup(hass)

    hass.bus.async_fire("mobile_app_notification_action", {
        "no_action_field": True
    })
    await hass.async_block_till_done()


async def test_coordinator_not_available_logs_warning(hass, caplog):
    """Test that missing coordinator logs a warning."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "http://127.0.0.1", "port": 7745, "token": ""},
    )
    entry.add_to_hass(hass)
    # Don't add to hass.data - simulate coordinator not being available

    notifications.async_setup(hass)

    hass.bus.async_fire("mobile_app_notification_action", {
        "action": "hoard:checkin:Drill"
    })
    await hass.async_block_till_done()

    assert "HomeHoard coordinator not available" in caplog.text
