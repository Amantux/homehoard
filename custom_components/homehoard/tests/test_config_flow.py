"""Config-flow tests: Supervisor discovery must refresh, never duplicate.

The add-on re-fires discovery on every boot, and a user may already have added
the same server by hand. Either way the result is one entry with a current
token — and an empty advertised token must never wipe a good stored one.
"""
from unittest.mock import AsyncMock, patch

from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homehoard.config_flow import HomeHoardConfigFlow
from custom_components.homehoard.const import CONF_HOST, CONF_PORT, CONF_TOKEN, DOMAIN

ADDON_HOST = "local-homehoard"
ADDON_PORT = 7745


def _discovery(token: str) -> HassioServiceInfo:
    return HassioServiceInfo(
        config={CONF_HOST: ADDON_HOST, CONF_PORT: ADDON_PORT, CONF_TOKEN: token},
        name="HomeHoard",
        slug="homehoard",
        uuid="1234",
    )


async def _start_hassio(hass, token: str, validate=None):
    with patch.object(
        HomeHoardConfigFlow, "_async_validate", validate or AsyncMock(return_value=None)
    ):
        return await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_HASSIO},
            data=_discovery(token),
        )


def _addon_entry(hass, token: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="homehoard_addon",
        data={CONF_HOST: ADDON_HOST, CONF_PORT: ADDON_PORT, CONF_TOKEN: token},
    )
    entry.add_to_hass(hass)
    return entry


async def test_hassio_rediscovery_updates_token_not_duplicate(hass):
    entry = _addon_entry(hass, "old-token")

    result = await _start_hassio(hass, "new-token")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_TOKEN] == "new-token"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_hassio_empty_token_does_not_overwrite(hass):
    entry = _addon_entry(hass, "good-token")

    result = await _start_hassio(hass, "")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_TOKEN] == "good-token"


async def test_hassio_unreachable_aborts_cannot_connect(hass):
    result = await _start_hassio(
        hass, "tok", validate=AsyncMock(side_effect=ClientError("refused"))
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_hassio_dedupes_manual_entry_same_host(hass):
    """A hand-added entry for the same host:port absorbs the discovery (token
    refreshed) instead of a second, discovered entry being offered."""
    manual = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{ADDON_HOST}:{ADDON_PORT}",
        data={CONF_HOST: ADDON_HOST.upper(), CONF_PORT: ADDON_PORT, CONF_TOKEN: "old"},
    )
    manual.add_to_hass(hass)

    result = await _start_hassio(hass, "minted")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert manual.data[CONF_TOKEN] == "minted"
    assert manual.unique_id == f"{ADDON_HOST}:{ADDON_PORT}"  # not re-keyed
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_hassio_manual_entry_empty_token_does_not_overwrite(hass):
    manual = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{ADDON_HOST}:{ADDON_PORT}",
        data={CONF_HOST: ADDON_HOST, CONF_PORT: ADDON_PORT, CONF_TOKEN: "good"},
    )
    manual.add_to_hass(hass)

    result = await _start_hassio(hass, "")

    assert result["reason"] == "already_configured"
    assert manual.data[CONF_TOKEN] == "good"


async def test_hassio_new_install_offers_confirm(hass):
    """No existing entry: discovery proceeds to the one-click confirm step."""
    result = await _start_hassio(hass, "tok")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hassio_confirm"
