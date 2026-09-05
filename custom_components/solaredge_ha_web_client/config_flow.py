"""Config flow for SolarEdge Web Client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_LIVE_INTERVAL,
    CONF_SITE_ID,
    DEFAULT_LIVE_INTERVAL_MINUTES,
    DOMAIN,
    MAX_LIVE_INTERVAL_MINUTES,
    MIN_LIVE_INTERVAL_MINUTES,
)
from .coordinator import async_validate_login

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SITE_ID): str,
    }
)
STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class SolarEdgeWebConfigFlow(ConfigFlow, domain=DOMAIN):
    """Collect portal credentials and a site ID."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_SITE_ID])
            self._abort_if_unique_id_configured()

            error = await async_validate_login(
                self.hass,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                user_input[CONF_SITE_ID],
            )
            if error is None:
                return self.async_create_entry(
                    title=f"SolarEdge {user_input[CONF_SITE_ID]}",
                    data=user_input,
                )
            errors["base"] = error

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauth. Only the password is in question."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect a replacement password, keeping username and site ID."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            candidate = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            error = await async_validate_login(
                self.hass,
                candidate[CONF_USERNAME],
                candidate[CONF_PASSWORD],
                candidate[CONF_SITE_ID],
            )
            if error is None:
                return self.async_update_reload_and_abort(entry, data=candidate)
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"site_id": entry.data[CONF_SITE_ID]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SolarEdgeWebOptionsFlow:
        """Return the options flow."""
        return SolarEdgeWebOptionsFlow()


class SolarEdgeWebOptionsFlow(OptionsFlow):
    """Adjust how often live data is polled."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the options step."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_LIVE_INTERVAL, DEFAULT_LIVE_INTERVAL_MINUTES
        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_LIVE_INTERVAL, default=current): vol.All(
                    cv.positive_int,
                    vol.Range(
                        min=MIN_LIVE_INTERVAL_MINUTES,
                        max=MAX_LIVE_INTERVAL_MINUTES,
                    ),
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
