"""Restock to-do list behaviour.

Drives the REAL coordinator with only the HTTP layer mocked, like
test_services.py. The two behaviours that matter:

  * A checkoff must NOT write to the backend. "I bought it" is not "it's
    counted on the shelf" — the honest inventory update happens in HomeHoard,
    so the entity must make zero non-GET requests, ever.
  * The checkoff memory reconciles against the feed: while the backend still
    suggests the item it stays hidden (checked off, not yet restocked), and
    once the backend drops it the memory is forgotten so a future restock
    need for the same item resurfaces.
"""
from homeassistant.components.todo import TodoItem, TodoItemStatus
from homeassistant.helpers import aiohttp_client
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homehoard.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    DOMAIN,
)
from custom_components.homehoard.coordinator import HomeHoardDataUpdateCoordinator
from custom_components.homehoard.todo import HomeHoardRestockTodoList

SUMMARY = "http://127.0.0.1:7745/api/v1/ha/summary"


def _summary(items):
    return {"health": True, "restock": {"count": len(items), "items": items}}


BATTERIES = {"id": "i1", "name": "AA batteries", "onHand": 1, "suggestedQuantity": 11}
BAGS = {"id": "i2", "name": "Bin bags", "onHand": 0, "suggestedQuantity": 2}


async def _setup(hass, aioclient_mock, items):
    aioclient_mock.get(SUMMARY, json=_summary(items))
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "http://127.0.0.1", CONF_PORT: 7745, CONF_TOKEN: ""},
    )
    entry.add_to_hass(hass)
    session = aiohttp_client.async_get_clientsession(hass)
    coordinator = HomeHoardDataUpdateCoordinator(hass, session, entry)
    await coordinator.async_refresh()
    entity = HomeHoardRestockTodoList(coordinator, entry)
    entity.hass = hass
    entity.entity_id = "todo.homehoard_restock_list"
    return entity, coordinator


def _non_get_calls(aioclient_mock):
    return [c for c in aioclient_mock.mock_calls if c[0].lower() != "get"]


async def test_items_mirror_the_restock_feed(hass, aioclient_mock):
    """Each suggestion becomes 'Name — buy N', keyed by the item id."""
    entity, _ = await _setup(hass, aioclient_mock, [BATTERIES, BAGS])

    items = entity.todo_items
    assert [i.summary for i in items] == ["AA batteries — buy 11", "Bin bags — buy 2"]
    assert [i.uid for i in items] == ["i1", "i2"]
    assert all(i.status == TodoItemStatus.NEEDS_ACTION for i in items)
    assert items[0].description == "On hand: 1"


async def test_checkoff_hides_the_item_and_writes_nothing(hass, aioclient_mock):
    """The headline guarantee: completion is local-only, never an inventory write."""
    entity, _ = await _setup(hass, aioclient_mock, [BATTERIES, BAGS])

    await entity.async_update_todo_item(
        TodoItem(summary="AA batteries — buy 11", uid="i1",
                 status=TodoItemStatus.COMPLETED)
    )

    assert [i.uid for i in entity.todo_items] == ["i2"]
    assert _non_get_calls(aioclient_mock) == [], "a checkoff must never POST/PUT"


async def test_checkoff_survives_a_refresh_that_still_lists_the_item(
    hass, aioclient_mock
):
    """Bought-but-not-yet-recorded must not bounce back on the next poll."""
    entity, coordinator = await _setup(hass, aioclient_mock, [BATTERIES, BAGS])
    await entity.async_update_todo_item(
        TodoItem(summary="x", uid="i1", status=TodoItemStatus.COMPLETED)
    )

    # Backend still suggests both (quantities not updated yet).
    await coordinator.async_refresh()

    assert [i.uid for i in entity.todo_items] == ["i2"]


async def test_checkoff_memory_resets_once_the_backend_drops_the_item(
    hass, aioclient_mock
):
    """When inventory is truly restocked the memory clears, so the NEXT time
    the item runs low it reappears instead of being hidden forever."""
    entity, coordinator = await _setup(hass, aioclient_mock, [BATTERIES, BAGS])
    await entity.async_update_todo_item(
        TodoItem(summary="x", uid="i1", status=TodoItemStatus.COMPLETED)
    )

    # Quantities updated in HomeHoard: the feed drops the item...
    aioclient_mock.clear_requests()
    aioclient_mock.get(SUMMARY, json=_summary([BAGS]))
    await coordinator.async_refresh()
    assert [i.uid for i in entity.todo_items] == ["i2"]

    # ...and when it runs low again later, it is suggested again.
    aioclient_mock.clear_requests()
    aioclient_mock.get(SUMMARY, json=_summary([BATTERIES, BAGS]))
    await coordinator.async_refresh()
    assert [i.uid for i in entity.todo_items] == ["i1", "i2"]


async def test_unchecking_restores_a_hidden_item(hass, aioclient_mock):
    entity, _ = await _setup(hass, aioclient_mock, [BATTERIES])
    await entity.async_update_todo_item(
        TodoItem(summary="x", uid="i1", status=TodoItemStatus.COMPLETED)
    )
    assert entity.todo_items == []

    await entity.async_update_todo_item(
        TodoItem(summary="x", uid="i1", status=TodoItemStatus.NEEDS_ACTION)
    )
    assert [i.uid for i in entity.todo_items] == ["i1"]


async def test_an_empty_or_missing_feed_is_an_empty_list(hass, aioclient_mock):
    """A summary without 'restock' (older backend) must not crash the entity."""
    entity, _ = await _setup(hass, aioclient_mock, [])
    assert entity.todo_items == []

    entity.coordinator.data = {"health": True}
    assert entity.todo_items == []
