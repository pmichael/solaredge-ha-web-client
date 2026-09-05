"""Config flow for SolarEdge Web Client."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .const import CONF_SITE_ID, DOMAIN
from .coordinator import async_validate_login

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SITE_ID): str,
    }
)


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
