from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from aiohttp import ClientError, ClientResponseError, ClientTimeout
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SUMMARY_PATH,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .helpers import build_url

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = ClientTimeout(total=10)


class HomeHoardOptionsFlow(config_entries.OptionsFlow):
    """Tune the poll interval after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=int(
                            current.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
                        ),
                    ): vol.All(int, vol.Range(min=30, max=3600)),
                }
            ),
        )


class HomeHoardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for HomeHoard (manual + Supervisor discovery)."""

    VERSION = 1

    def __init__(self) -> None:
        self._hassio_discovery: HassioServiceInfo | None = None

    @staticmethod
    def async_get_options_flow(config_entry) -> HomeHoardOptionsFlow:
        return HomeHoardOptionsFlow()

    # ------------------------------------------------------------------
    # Supervisor discovery (add-on installed) — near-zero typing.
    # ------------------------------------------------------------------
    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> FlowResult:
        self._hassio_discovery = discovery_info
        await self.async_set_unique_id("homehoard_addon")
        self._abort_if_unique_id_configured()

        host = discovery_info.config.get(CONF_HOST, DEFAULT_HOST)
        port = int(discovery_info.config.get(CONF_PORT, DEFAULT_PORT))
        try:
            await self._async_validate(host, port)
        except (ClientError, asyncio.TimeoutError):
            return self.async_abort(reason="cannot_connect")
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        assert self._hassio_discovery is not None
        if user_input is not None:
            return self.async_create_entry(
                title="HomeHoard (add-on)",
                data={
                    CONF_HOST: self._hassio_discovery.config.get(CONF_HOST, DEFAULT_HOST),
                    CONF_PORT: int(
                        self._hassio_discovery.config.get(CONF_PORT, DEFAULT_PORT)
                    ),
                    # Add-on runs auth-disabled behind ingress — no token needed.
                    CONF_TOKEN: "",
                },
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="hassio_confirm",
            description_placeholders={"addon": "HomeHoard"},
        )

    # ------------------------------------------------------------------
    # Manual setup
    # ------------------------------------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip().rstrip("/")
            port = int(user_input[CONF_PORT])
            token = str(user_input.get(CONF_TOKEN, "")).strip()
            # Idempotent: adding the same host twice (or on top of the
            # auto-discovered add-on) just points at the existing entry.
            await self.async_set_unique_id(f"{host}:{port}".lower())
            self._abort_if_unique_id_configured()
            try:
                await self._async_validate(host, port, token)
            except ClientResponseError as exc:
                if exc.status in (401, 403):
                    # Auth is on and the token is missing/invalid.
                    errors["base"] = "invalid_auth"
                else:
                    _LOGGER.warning("HomeHoard returned %s", exc.status)
                    errors["base"] = "cannot_connect"
            except (ClientError, asyncio.TimeoutError) as exc:
                _LOGGER.warning("Cannot reach HomeHoard: %s", exc)
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title="HomeHoard",
                    data={CONF_HOST: host, CONF_PORT: port, CONF_TOKEN: token},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                    vol.Optional(CONF_TOKEN, default=""): str,
                }
            ),
            errors=errors,
        )

    async def _async_validate(self, host: str, port: int, token: str = "") -> None:
        """Probe an authenticated endpoint so an auth-on server without a valid
        token fails here (401) instead of silently going unavailable later."""
        session = aiohttp_client.async_get_clientsession(self.hass)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        url = build_url(host, port, DEFAULT_SUMMARY_PATH)
        async with session.get(url, headers=headers, timeout=_TIMEOUT) as response:
            response.raise_for_status()
