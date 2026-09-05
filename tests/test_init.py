"""Entry setup, teardown and the device tree."""

from unittest.mock import AsyncMock, patch

import aiohttp
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.solaredge_ha_web_client.const import CONF_LIVE_INTERVAL, DOMAIN
from custom_components.solaredge_ha_web_client.entity import SolarEdgeWebEntity

from .test_coordinator_live import _client, _coordinator, _entry


async def _setup(hass: HomeAssistant, client: object) -> object:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.solaredge_ha_web_client.coordinator.SolarEdgeWeb",
        return_value=client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_setup_succeeds_and_stores_the_coordinator(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass, _client())
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not None


async def test_devices_nest_optimizer_under_inverter_under_site(
    hass: HomeAssistant,
) -> None:
    """Flat devices would make twenty optimizers unreadable in the UI."""
    entry = await _setup(hass, _client())
    registry = dr.async_get(hass)

    site = registry.async_get_device_by_identifier((DOMAIN, "SITE-TEST"), entry.entry_id)
    inverter = registry.async_get_device_by_identifier((DOMAIN, "INV-TEST-1"), entry.entry_id)
    optimizer = registry.async_get_device_by_identifier((DOMAIN, "OPT-TEST-1"), entry.entry_id)

    assert site is not None
    assert inverter is not None
    assert optimizer is not None
    assert inverter.via_device_id == site.id
    assert optimizer.via_device_id == inverter.id


async def test_setup_retries_when_the_layout_is_unreachable(
    hass: HomeAssistant,
) -> None:
    client = _client(async_get_equipment=AsyncMock(side_effect=aiohttp.ClientError("boom")))
    entry = await _setup(hass, client)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_succeeds(hass: HomeAssistant) -> None:
    entry = await _setup(hass, _client())
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_changing_options_reloads_the_entry(hass: HomeAssistant) -> None:
    """A new interval must take effect without a restart."""
    entry = await _setup(hass, _client())
    with patch(
        "custom_components.solaredge_ha_web_client.coordinator.SolarEdgeWeb",
        return_value=_client(),
    ):
        hass.config_entries.async_update_entry(entry, options={CONF_LIVE_INTERVAL: 30})
        await hass.async_block_till_done()

    assert entry.runtime_data.update_interval.total_seconds() == 30 * 60


async def test_entity_stays_available_after_one_failed_live_cycle(
    hass: HomeAssistant,
) -> None:
    """UpdateFailed clears last_update_success; last-known data must still show."""
    coordinator = await _coordinator(hass, _client())
    await coordinator.async_refresh()
    assert coordinator.data is not None

    error = AsyncMock(side_effect=aiohttp.ClientError("boom"))
    coordinator.client.async_get_optimizer_data = error
    coordinator.client.async_get_optimizer_temperatures = error
    coordinator.client.async_get_inverter_data = error
    coordinator.client.async_get_live_power = error
    coordinator.client.async_get_alerts = error
    await coordinator.async_refresh()

    entity = SolarEdgeWebEntity(coordinator)
    assert coordinator.last_update_success is False
    assert coordinator.data is not None
    assert coordinator.data_is_stale is False
    assert entity.available is True
