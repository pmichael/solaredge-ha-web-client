"""Config flow for SolarEdge Web Client."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from solaredge_web import SolarEdgeWeb

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_SITE_ID, DOMAIN, LOGGER
from .coordinator import map_client_error

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

    async def _async_validate(self, user_input: dict[str, Any]) -> str | None:
        """Return an error key, or None when the credentials work.

        `async_get_site_information` both authenticates and proves the site is
        visible to this account, so one request validates the whole form.
        """
        client = SolarEdgeWeb(
            username=user_input[CONF_USERNAME],
            password=user_input[CONF_PASSWORD],
            site_id=user_input[CONF_SITE_ID],
            session=async_get_clientsession(self.hass),
        )
        try:
            await client.async_get_site_information()
        except Exception as err:  # noqa: BLE001
            mapped = map_client_error(err, "site information")
            if isinstance(mapped, ConfigEntryAuthFailed):
                return "invalid_auth"
            LOGGER.debug("Validation failed: %s", mapped)
            return "cannot_connect"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_SITE_ID])
            self._abort_if_unique_id_configured()

            error = await self._async_validate(user_input)
            if error is None:
                return self.async_create_entry(
                    title=f"SolarEdge {user_input[CONF_SITE_ID]}",
                    data=user_input,
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
