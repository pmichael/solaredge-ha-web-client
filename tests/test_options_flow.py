"""Options flow."""

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solaredge_ha_web_client.const import (
    CONF_LIVE_INTERVAL,
    DEFAULT_LIVE_INTERVAL_MINUTES,
    DOMAIN,
    MAX_LIVE_INTERVAL_MINUTES,
    MIN_LIVE_INTERVAL_MINUTES,
)

from .fixtures import SITE_ID
from .test_config_flow_reauth import ENTRY_DATA


async def test_options_flow_stores_the_interval(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SITE_ID, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LIVE_INTERVAL: 20}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LIVE_INTERVAL] == 20


@pytest.mark.parametrize(
    "value",
    [MIN_LIVE_INTERVAL_MINUTES - 1, MAX_LIVE_INTERVAL_MINUTES + 1],
)
async def test_options_flow_rejects_out_of_range(
    hass: HomeAssistant, value: int
) -> None:
    """Below the floor the API has nothing new to give."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SITE_ID, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_LIVE_INTERVAL: value}
        )


async def test_default_is_offered(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SITE_ID, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})

    assert entry.options[CONF_LIVE_INTERVAL] == DEFAULT_LIVE_INTERVAL_MINUTES
