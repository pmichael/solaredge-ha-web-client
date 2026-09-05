"""Config flow: user step."""

from unittest.mock import AsyncMock, Mock, patch

import aiohttp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solaredge_ha_web_client.const import CONF_SITE_ID, DOMAIN
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .fixtures import SITE_ID, SITE_INFORMATION

USER_INPUT = {
    CONF_USERNAME: "user@example.com",
    CONF_PASSWORD: "hunter2",
    CONF_SITE_ID: SITE_ID,
}


def _client(side_effect: object = None) -> Mock:
    client = Mock()
    client.async_get_site_information = AsyncMock(
        return_value=SITE_INFORMATION, side_effect=side_effect
    )
    return client


async def test_user_step_creates_entry(hass: HomeAssistant) -> None:
    with (
        patch(
            "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
            return_value=_client(),
        ),
        patch(
            "custom_components.solaredge_ha_web_client.async_setup_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT
    assert result["result"].unique_id == SITE_ID


async def test_shows_form_with_no_input(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_invalid_auth(hass: HomeAssistant) -> None:
    error = aiohttp.ClientResponseError(
        request_info=Mock(), history=(), status=401, message="denied"
    )
    with patch(
        "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
        return_value=_client(side_effect=error),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_cannot_connect(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
        return_value=_client(side_effect=aiohttp.ClientError("boom")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_site_aborts(hass: HomeAssistant) -> None:
    """Two entries for one site would double every request and statistic."""
    MockConfigEntry(domain=DOMAIN, unique_id=SITE_ID, data=USER_INPUT).add_to_hass(hass)

    with patch(
        "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
        return_value=_client(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_recovers_after_a_failed_attempt(hass: HomeAssistant) -> None:
    """A typo must be correctable without restarting the flow."""
    with patch(
        "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
        return_value=_client(side_effect=aiohttp.ClientError("boom")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )

    with (
        patch(
            "custom_components.solaredge_ha_web_client.config_flow.SolarEdgeWeb",
            return_value=_client(),
        ),
        patch(
            "custom_components.solaredge_ha_web_client.async_setup_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
