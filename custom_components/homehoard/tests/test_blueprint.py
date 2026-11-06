"""The digest blueprint, proven against what Home Assistant actually does with it.

The file is loaded by HA's own Blueprint class and run as a real automation,
reading real sensor states built from a mocked /ha/summary. Every button it
produces is then tapped on the real event bus, which is what proves a button is
never dead: the old blueprint's "hoard:restock" (no id) validated fine and did
nothing at all.
"""
import importlib
import pathlib
import shutil

import pytest
from homeassistant.components.notify.const import NOTIFY_SERVICE_SCHEMA
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.json import json_dumps
from homeassistant.setup import async_setup_component
from homeassistant.util import yaml as yaml_util
from homeassistant.util.json import json_loads
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.homehoard import notifications, sensor
from custom_components.homehoard.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    DOMAIN,
)

# hassfest scans every .py under the integration, tests included, and fails it for
# importing a component the manifest doesn't depend on. Only this test uses blueprint,
# and the shipped manifest must not claim a dependency it doesn't have, so it is
# loaded by name. An ordinary import here turns the blocking HA validate job red.
importer = importlib.import_module("homeassistant.components.blueprint.importer")
Blueprint = importlib.import_module("homeassistant.components.blueprint.models").Blueprint
BLUEPRINT_SCHEMA = importlib.import_module(
    "homeassistant.components.blueprint.schemas"
).BLUEPRINT_SCHEMA

REPO = pathlib.Path(__file__).resolve().parents[3]
RELATIVE = "blueprints/automation/homehoard/homehoard_daily_digest.yaml"
BLUEPRINT = REPO / RELATIVE
RAW_URL = f"https://raw.githubusercontent.com/Amantux/homehoard/main/{RELATIVE}"

BASE = "http://127.0.0.1:7745"
SUMMARY = f"{BASE}/api/v1/ha/summary"

# The harness runs in US/Pacific. The digest is set for 08:00 local.
BEFORE_TRIGGER = "2026-01-15 07:59:30-08:00"
AT_TRIGGER = "2026-01-15 08:00:00-08:00"


def _low(item_id, name="AA batteries", **extra):
    return {
        "id": item_id, "name": name, "onHand": 1, "suggestedQuantity": 11,
        "oneTap": True, **extra,
    }


def _entry(entry_id, item_id="i9", overdue=True, name="Filter change", item_name="Furnace"):
    return {
        "id": entry_id, "name": name, "itemId": item_id, "itemName": item_name,
        "scheduled": "2026-01-01", "overdue": overdue,
    }


def _summary(low=(), entries=(), count=None):
    return {
        "health": True,
        "restock": {"count": len(low) if count is None else count, "items": list(low)},
        "maintenance": {
            "overdue": sum(1 for e in entries if e["overdue"]),
            "upcoming30": 0,
            "entries": list(entries),
        },
        "totals": {},
    }


def _load_file():
    return yaml_util.load_yaml_dict(str(BLUEPRINT))


@pytest.fixture(autouse=True)
async def _unload_entries(hass):
    """Unload what a test left loaded: a refresh leaves a cooldown timer running."""
    yield
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)


@pytest.fixture
async def digest(hass, aioclient_mock, tmp_path, freezer):
    """Run the blueprint as a real automation; returns the notify calls it made."""

    async def _run(
        low=(), entries=(), notifier="mobile_app_phone", count=None, device_name=None, also=None
    ):
        freezer.move_to(BEFORE_TRIGGER)
        # Where HA looks for it, which is also where an import by URL saves it.
        folder = tmp_path / "blueprints" / "automation" / "Amantux"
        folder.mkdir(parents=True)
        shutil.copy(BLUEPRINT, folder / BLUEPRINT.name)
        hass.config.config_dir = str(tmp_path)

        aioclient_mock.get(SUMMARY, json=_summary(low, entries, count))
        entry = MockConfigEntry(
            domain=DOMAIN, data={CONF_HOST: "http://127.0.0.1", CONF_PORT: 7745, CONF_TOKEN: ""}
        )
        entry.add_to_hass(hass)
        if device_name:
            devices = dr.async_get(hass)
            device = devices.async_get_or_create(
                config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)}
            )
            devices.async_update_device(device.id, name_by_user=device_name)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        if also:
            await also(entry)

        # With notify's real schema: it rejects a message or data of the wrong shape.
        calls = async_mock_service(
            hass, "notify", "mobile_app_phone", schema=NOTIFY_SERVICE_SCHEMA
        )
        assert await async_setup_component(
            hass,
            "automation",
            {
                "automation": {
                    "use_blueprint": {
                        "path": f"Amantux/{BLUEPRINT.name}",
                        "input": {"time": "08:00:00", "notifier": notifier},
                    }
                }
            },
        )
        await hass.async_block_till_done()

        freezer.move_to(AT_TRIGGER)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        return calls

    yield _run

    # Tomorrow's 08:00 timer would otherwise outlive the test.
    if hass.services.has_service("automation", "turn_off"):
        await hass.services.async_call(
            "automation", "turn_off", {"entity_id": "all"}, blocking=True
        )


def _buttons(call):
    return call.data["data"]["actions"]


async def _tap_all(hass, call):
    for button in _buttons(call):
        hass.bus.async_fire(
            "mobile_app_notification_action", {"action": button["action"]}
        )
        await hass.async_block_till_done()


def _writes(aioclient_mock):
    return [
        (c[0].lower(), str(c[1])) for c in aioclient_mock.mock_calls if c[0].lower() != "get"
    ]


# --- the file itself --------------------------------------------------------

def test_blueprint_is_valid_and_asks_for_time_and_notifier():
    blueprint = Blueprint(_load_file(), expected_domain="automation", schema=BLUEPRINT_SCHEMA)

    assert blueprint.validate() is None
    assert set(blueprint.inputs) == {"time", "notifier"}


def test_blueprint_lives_where_its_source_url_says():
    """HA only loads blueprints from <config>/blueprints/<domain>/, so it ships by
    URL. Moving or renaming the file without updating this URL breaks every
    import and re-import, and nothing else would notice."""
    blueprint = Blueprint(_load_file(), schema=BLUEPRINT_SCHEMA)

    assert blueprint.metadata["source_url"] == RAW_URL
    assert BLUEPRINT.is_file()
    assert not (REPO / "custom_components" / "homehoard" / "blueprints").exists()


def test_blueprint_minimum_matches_what_hacs_admits():
    declared = json_loads((REPO / "hacs.json").read_text())["homeassistant"]

    assert _load_file()["blueprint"]["homeassistant"]["min_version"] == declared


async def test_blueprint_imports_by_its_url(hass, aioclient_mock):
    """Home Assistant's own importer, handed the URL the docs tell people to use."""
    aioclient_mock.get(RAW_URL, text=BLUEPRINT.read_text())

    imported = await importer.fetch_blueprint_from_url(hass, RAW_URL)

    assert imported.blueprint.domain == "automation"
    assert imported.blueprint.metadata["source_url"] == RAW_URL
    assert imported.suggested_filename == "Amantux/homehoard_daily_digest"


# --- what it sends ----------------------------------------------------------

async def test_digest_lists_what_is_low_and_overdue(hass, digest):
    calls = await digest(
        low=[_low("i1"), _low("i2", name="Bin bags", suggestedQuantity=2)],
        entries=[_entry("e1")],
    )

    assert len(calls) == 1
    assert calls[0].domain == "notify" and calls[0].service == "mobile_app_phone"
    assert calls[0].data["title"] == "HomeHoard"
    assert calls[0].data["message"] == (
        "Running low (2): AA batteries (buy 11), Bin bags (buy 2).\n"
        "Maintenance overdue (1): Filter change (Furnace)."
    )
    assert calls[0].data["data"]["tag"] == "homehoard-digest"
    assert calls[0].data["data"]["timeout"] == 86400


async def test_every_button_is_routed_and_reaches_the_server(hass, digest, aioclient_mock):
    """The contract: each button parses to a handler, and tapping it sends the request."""
    aioclient_mock.post(f"{BASE}/api/v1/restock/i1/restocked", json={})
    aioclient_mock.post(f"{BASE}/api/v1/restock/i2/restocked", json={})
    aioclient_mock.put(f"{BASE}/api/v1/items/i9/maintenance/e1", json={})
    calls = await digest(low=[_low("i1"), _low("i2", name="Bin bags")], entries=[_entry("e1")])

    assert _buttons(calls[0]) == [
        {"action": "hoard:restock:i1:11", "title": "Bought 11 AA batteries"},
        {"action": "hoard:restock:i2:11", "title": "Bought 11 Bin bags"},
        {"action": "hoard:maintenance_done:i9:e1", "title": "Done: Furnace - Filter change"},
    ]
    assert all(notifications._route(b["action"]) for b in _buttons(calls[0]))

    await _tap_all(hass, calls[0])

    assert _writes(aioclient_mock) == [
        ("post", f"{BASE}/api/v1/restock/i1/restocked"),
        ("post", f"{BASE}/api/v1/restock/i2/restocked"),
        ("put", f"{BASE}/api/v1/items/i9/maintenance/e1"),
    ]


@pytest.mark.parametrize(
    ("suggested", "shown"), [(3, "3"), (2.625, "2.625"), (0.1, "0.1"), (999999999.999, "999999999.999")]
)
async def test_the_message_the_button_and_the_request_carry_one_number(
    hass, digest, aioclient_mock, suggested, shown
):
    """The tap adds what the message said to buy, in every form a quantity can take.

    The server's suggestion at tap time plays no part: with an empty body it would
    answer with whatever it suggests by then, and the count would be wrong by the
    difference, with nothing on the phone to show it.
    """
    aioclient_mock.post(f"{BASE}/api/v1/restock/i1/restocked", json={})
    calls = await digest(low=[_low("i1", name="Cells", suggestedQuantity=suggested)])

    assert f"Cells (buy {shown})" in calls[0].data["message"]
    assert _buttons(calls[0]) == [
        {"action": f"hoard:restock:i1:{shown}", "title": f"Bought {shown} Cells"}
    ]

    await _tap_all(hass, calls[0])

    writes = [c for c in aioclient_mock.mock_calls if c[0].lower() == "post"]
    assert [c[2] for c in writes] == [{"quantity": suggested}]


async def test_real_uuids_route(hass, digest, aioclient_mock):
    item, entry = "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b", "0d9e8f7a-6b5c-4d3e-a2f1-0e9d8c7b6a5f"
    aioclient_mock.post(f"{BASE}/api/v1/restock/{item}/restocked", json={})
    aioclient_mock.put(f"{BASE}/api/v1/items/{item}/maintenance/{entry}", json={})
    calls = await digest(low=[_low(item)], entries=[_entry(entry, item_id=item)])

    await _tap_all(hass, calls[0])

    assert len(_writes(aioclient_mock)) == 2


async def test_the_actions_survive_the_trip_to_the_phone(hass, digest):
    """mobile_app JSON-encodes the payload: it must come out as a plain list of dicts."""
    calls = await digest(low=[_low("i1")], entries=[_entry("e1")])

    sent = json_loads(json_dumps(calls[0].data["data"]))

    assert sent["actions"] == [
        {"action": "hoard:restock:i1:11", "title": "Bought 11 AA batteries"},
        {"action": "hoard:maintenance_done:i9:e1", "title": "Done: Furnace - Filter change"},
    ]


@pytest.mark.parametrize(
    ("low_count", "overdue_count", "expected_bought", "expected_done"),
    [(5, 0, 3, 0), (0, 5, 0, 3), (5, 5, 2, 1), (1, 5, 1, 2), (5, 1, 2, 1), (1, 1, 1, 1)],
)
async def test_never_more_than_androids_three_buttons(
    hass, digest, low_count, overdue_count, expected_bought, expected_done
):
    calls = await digest(
        low=[_low(f"i{n}", name=f"Item {n}") for n in range(low_count)],
        entries=[_entry(f"e{n}", name=f"Job {n}") for n in range(overdue_count)],
    )

    actions = [b["action"] for b in _buttons(calls[0])]
    assert sum(a.startswith("hoard:restock:") for a in actions) == expected_bought
    assert sum(a.startswith("hoard:maintenance_done:") for a in actions) == expected_done


async def test_the_buttons_go_to_the_rows_listed_first(hass, digest):
    """The feeds are lowest-stock and oldest first, so that is who gets the buttons."""
    calls = await digest(
        low=[_low(f"i{n}", name=f"Item {n}") for n in range(3)],
        entries=[_entry(f"e{n}", name=f"Job {n}") for n in range(3)],
    )

    assert [b["action"] for b in _buttons(calls[0])] == [
        "hoard:restock:i0:11", "hoard:restock:i1:11", "hoard:maintenance_done:i9:e0",
    ]


async def test_the_message_counts_everything_and_names_ten_of_each(hass, digest):
    """The count is the server's: the feed itself stops at 20 rows."""
    calls = await digest(
        low=[_low(f"i{n}", name=f"Item {n}") for n in range(12)],
        entries=[_entry(f"e{n}", name=f"Job {n}") for n in range(12)],
        count=25,
    )

    message = calls[0].data["message"]
    assert hass.states.get("sensor.homehoard_restock_needed").state == "25"
    assert "Running low (25): Item 0 (buy 11)" in message
    assert "Maintenance overdue (12): Job 0 (Furnace)" in message
    assert "Item 9 (buy 11)." in message and "Item 10" not in message
    assert "Job 9 (Furnace)." in message and "Job 10" not in message


# --- buttons nobody can mistake for another ---------------------------------

async def test_the_same_job_on_different_items_reads_differently(hass, digest):
    """All three used to read "Done: Filter change" and point at different items."""
    calls = await digest(entries=[
        _entry("e1", item_id="furnace", item_name="Furnace"),
        _entry("e2", item_id="fridge", item_name="Fridge"),
        _entry("e3", item_id="dryer", item_name="Dryer"),
    ])

    assert _buttons(calls[0]) == [
        {"action": "hoard:maintenance_done:furnace:e1", "title": "Done: Furnace - Filter change"},
        {"action": "hoard:maintenance_done:fridge:e2", "title": "Done: Fridge - Filter change"},
        {"action": "hoard:maintenance_done:dryer:e3", "title": "Done: Dryer - Filter change"},
    ]


async def test_same_named_items_are_told_apart_by_the_amount(hass, digest):
    calls = await digest(low=[
        _low("a", name="Batteries", suggestedQuantity=3),
        _low("b", name="Batteries", suggestedQuantity=40),
    ])

    assert _buttons(calls[0]) == [
        {"action": "hoard:restock:a:3", "title": "Bought 3 Batteries"},
        {"action": "hoard:restock:b:40", "title": "Bought 40 Batteries"},
    ]


async def test_rows_nothing_tells_apart_are_listed_without_a_button(hass, digest):
    """Two buttons reading the same could act on the wrong one, with no undo."""
    calls = await digest(
        low=[
            _low("a", name="Batteries", suggestedQuantity=3),
            _low("b", name="Batteries", suggestedQuantity=3),
            _low("c", name="Bin bags"),
        ],
        entries=[_entry("e1", item_id="x"), _entry("e2", item_id="y")],
    )

    assert calls[0].data["message"].count("Batteries (buy 3)") == 2
    assert calls[0].data["message"].count("Filter change (Furnace)") == 2
    assert [b["action"] for b in _buttons(calls[0])] == ["hoard:restock:c:11"]


# --- when it stays quiet or holds back --------------------------------------

async def test_nothing_to_report_sends_nothing(hass, digest):
    assert await digest() == []


async def test_upcoming_maintenance_alone_sends_nothing(hass, digest):
    """The sensor's entries include what is merely scheduled; that is not news."""
    assert await digest(entries=[_entry("e1", overdue=False)]) == []


async def test_upcoming_maintenance_never_gets_a_button(hass, digest):
    calls = await digest(
        low=[_low("i1")], entries=[_entry("e1", overdue=False, name="Next month's job")]
    )

    assert [b["action"] for b in _buttons(calls[0])] == ["hoard:restock:i1:11"]
    assert "Next month's job" not in calls[0].data["message"]


async def test_an_item_in_several_places_is_listed_without_a_button(hass, digest):
    """The server would answer 409, so "Bought" would be a dead button."""
    calls = await digest(low=[_low("i1", oneTap=False, name="Split item"), _low("i2")])

    assert "Split item" in calls[0].data["message"]
    assert [b["action"] for b in _buttons(calls[0])] == ["hoard:restock:i2:11"]


async def test_a_server_too_old_to_say_gets_no_bought_buttons(hass, digest):
    """No oneTap means no way to know the endpoint exists. Report, but offer nothing."""
    item = _low("i1")
    del item["oneTap"]

    calls = await digest(low=[item])

    assert "AA batteries" in calls[0].data["message"]
    assert _buttons(calls[0]) == []


async def test_an_integration_too_old_to_hear_a_tap_gets_no_buttons(hass, digest, monkeypatch):
    """The blueprint goes live by URL at merge, and a released integration with no
    listener has the maintenance sensor but not the restock one. A Done button there
    would be dead, so a missing restock sensor means none are offered."""
    monkeypatch.setattr(
        sensor, "SENSORS", tuple(d for d in sensor.SENSORS if d.key != "restock_needed")
    )

    calls = await digest(entries=[_entry("e1")])

    assert hass.states.get("sensor.homehoard_restock_needed") is None
    assert calls[0].data["message"] == "Maintenance overdue (1): Filter change (Furnace)."
    assert _buttons(calls[0]) == []


# --- names are data ---------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    [
        "Kid's \"AAA\" cells",
        "{{ 7 * 7 }}",
        "{% raw %}",
        "Glue: wood/metal #2 ?",
        "Ünï çødé",
        "[1, 2]",
    ],
)
async def test_any_item_name_comes_through_verbatim(hass, digest, aioclient_mock, name):
    aioclient_mock.post(f"{BASE}/api/v1/restock/i1/restocked", json={})
    calls = await digest(low=[_low("i1", name=name)])

    assert name in calls[0].data["message"]
    assert _buttons(calls[0]) == [{"action": "hoard:restock:i1:11", "title": f"Bought 11 {name}"}]

    await _tap_all(hass, calls[0])
    assert _writes(aioclient_mock) == [("post", f"{BASE}/api/v1/restock/i1/restocked")]


async def test_maintenance_with_no_name_falls_back_to_the_item(hass, digest):
    calls = await digest(entries=[_entry("e1", name="")])

    assert calls[0].data["message"] == "Maintenance overdue (1): Furnace."
    assert _buttons(calls[0])[0]["title"] == "Done: Furnace"


# --- the inputs -------------------------------------------------------------

async def test_a_pasted_notify_prefix_still_works(hass, digest):
    calls = await digest(low=[_low("i1")], notifier="notify.mobile_app_phone")

    assert len(calls) == 1


# --- which sensors, which server --------------------------------------------

async def test_a_renamed_device_keeps_the_digest_working(hass, digest):
    """An entity id starts with the device's name, so a hard-coded id would silently
    report nothing: to the person, that looks exactly like a quiet day."""
    calls = await digest(low=[_low("i1")], entries=[_entry("e1")], device_name="Stuff")

    assert hass.states.get("sensor.stuff_restock_needed").state == "1"
    assert hass.states.get("sensor.homehoard_restock_needed") is None
    assert calls[0].data["message"] == (
        "Running low (1): AA batteries (buy 11).\n"
        "Maintenance overdue (1): Filter change (Furnace)."
    )
    assert len(_buttons(calls[0])) == 2


@pytest.mark.parametrize("reload_first", [False, True])
async def test_with_two_servers_it_reports_on_the_one_its_buttons_act_on(
    hass, digest, aioclient_mock, reload_first
):
    """Ids are UUIDs, so a button landing on the other server would just do nothing.
    A reload changes which one is "first", and it has to change for both."""
    other = "http://127.0.0.2:7745"
    aioclient_mock.get(f"{other}/api/v1/ha/summary", json=_summary([_low("i2", name="Theirs")]))
    aioclient_mock.post(f"{BASE}/api/v1/restock/i1/restocked", json={})
    aioclient_mock.post(f"{other}/api/v1/restock/i2/restocked", json={})

    async def second_server(first):
        second = MockConfigEntry(
            domain=DOMAIN, data={CONF_HOST: "http://127.0.0.2", CONF_PORT: 7745, CONF_TOKEN: ""}
        )
        second.add_to_hass(hass)
        assert await hass.config_entries.async_setup(second.entry_id)
        await hass.async_block_till_done()
        if reload_first:
            assert await hass.config_entries.async_reload(first.entry_id)
            await hass.async_block_till_done()

    calls = await digest(low=[_low("i1", name="Ours")], also=second_server)

    name, url = (
        ("Theirs", f"{other}/api/v1/restock/i2/restocked")
        if reload_first
        else ("Ours", f"{BASE}/api/v1/restock/i1/restocked")
    )
    assert calls[0].data["message"] == f"Running low (1): {name} (buy 11)."

    await _tap_all(hass, calls[0])

    assert _writes(aioclient_mock) == [("post", url)]
