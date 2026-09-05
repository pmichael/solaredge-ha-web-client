"""Reauth flow."""

from unittest.mock import AsyncMock, Mock, patch

import aiohttp
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solaredge_ha_web_client.const import CONF_SITE_ID, DOMAIN

from .fixtures import SITE_ID, SITE_INFORMATION

ENTRY_DATA = {
    CONF_USERNAME: "user@example.com",
    CONF_PASSWORD: "old-password",
    CONF_SITE_ID: SITE_ID,
}


def _client(side_effect: object = None) -> Mock:
    client = Mock()
    client.async_get_site_information = AsyncMock(
        return_value=SITE_INFORMATION, side_effect=side_effect
    )
    return client


async def test_reauth_updates_only_the_password(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SITE_ID, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert set(result["data_schema"].schema) == {CONF_PASSWORD}

    with (
        patch(
            "custom_components.solaredge_ha_web_client.coordinator.SolarEdgeWeb",
            return_value=_client(),
        ),
        patch(
            "custom_components.solaredge_ha_web_client.async_setup_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new-password"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"
    assert entry.data[CONF_USERNAME] == "user@example.com"
    assert entry.data[CONF_SITE_ID] == SITE_ID


async def test_reauth_rejects_a_still_wrong_password(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SITE_ID, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)

    error = aiohttp.ClientResponseError(
        request_info=Mock(), history=(), status=401, message="denied"
    )
    with patch(
        "custom_components.solaredge_ha_web_client.coordinator.SolarEdgeWeb",
        return_value=_client(side_effect=error),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "still-wrong"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_PASSWORD] == "old-password"
