"""Sensor entities."""

from unittest.mock import AsyncMock

import aiohttp
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.solaredge_ha_web_client.const import MAX_CONSECUTIVE_FAILURES

from .test_coordinator_live import _client
from .test_init import _setup


async def test_optimizer_power_is_enabled_and_correct(
    hass: HomeAssistant,
) -> None:
    await _setup(hass, _client())
    state = hass.states.get("sensor.optimizer_1_1_1_power")
    assert state is not None
    assert state.state == "198.0"
    assert state.attributes["device_class"] == SensorDeviceClass.POWER
    assert state.attributes["state_class"] == SensorStateClass.MEASUREMENT
    assert state.attributes["unit_of_measurement"] == "W"


async def test_optimizer_temperature_is_named_as_a_daily_maximum(
    hass: HomeAssistant,
) -> None:
    """The endpoint returns a max over a range, so the name must not imply live."""
    await _setup(hass, _client())
    state = hass.states.get("sensor.optimizer_1_1_1_max_temperature_today")
    assert state is not None
    assert state.state == "41.5"
    assert state.attributes["device_class"] == SensorDeviceClass.TEMPERATURE


async def test_voltage_and_current_are_disabled_by_default(
    hass: HomeAssistant,
) -> None:
    """Twenty optimizers times five sensors is mostly noise."""
    entry = await _setup(hass, _client())
    registry = er.async_get(hass)

    for suffix in ("module_voltage", "optimizer_voltage", "current", "last_measurement"):
        rows = [
            e
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
            if e.unique_id.endswith(suffix)
        ]
        assert rows, f"no entity found for {suffix}"
        assert all(e.disabled_by is er.RegistryEntryDisabler.INTEGRATION for e in rows)


async def test_peak_power_has_no_device_or_state_class(
    hass: HomeAssistant,
) -> None:
    """A kWp nameplate rating must not use a power device class."""
    await _setup(hass, _client())
    state = hass.states.get("sensor.solaredge_site_site_test_peak_power")
    assert state is not None
    assert state.state == "11.7"
    assert "device_class" not in state.attributes
    assert "state_class" not in state.attributes


async def test_cloud_sensors_are_labelled_cloud(hass: HomeAssistant) -> None:
    """Without the qualifier these sit next to Modbus entities, disagreeing."""
    await _setup(hass, _client())
    state = hass.states.get("sensor.solaredge_site_site_test_site_power_cloud")
    assert state is not None
    assert "Cloud" in state.attributes["friendly_name"]


async def test_last_successful_update_is_present(hass: HomeAssistant) -> None:
    """Availability holds stale values, so staleness must be observable."""
    await _setup(hass, _client())
    state = hass.states.get("sensor.solaredge_site_site_test_last_successful_update")
    assert state is not None
    assert state.state != STATE_UNKNOWN


async def test_failed_section_yields_unknown_not_a_stale_number(
    hass: HomeAssistant,
) -> None:
    client = _client(
        async_get_optimizer_temperatures=AsyncMock(side_effect=aiohttp.ClientError("boom"))
    )
    await _setup(hass, client)

    assert hass.states.get("sensor.optimizer_1_1_1_power").state == "198.0"
    assert hass.states.get("sensor.optimizer_1_1_1_max_temperature_today").state == STATE_UNKNOWN


async def test_sustained_failure_marks_entities_unavailable(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass, _client())
    coordinator = entry.runtime_data

    error = AsyncMock(side_effect=aiohttp.ClientError("boom"))
    coordinator.client.async_get_optimizer_data = error
    coordinator.client.async_get_optimizer_temperatures = error
    coordinator.client.async_get_inverter_data = error
    coordinator.client.async_get_live_power = error
    coordinator.client.async_get_alerts = error

    for _ in range(MAX_CONSECUTIVE_FAILURES):
        await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.optimizer_1_1_1_power").state == STATE_UNAVAILABLE


async def test_unique_ids_are_stable_and_distinct(hass: HomeAssistant) -> None:
    entry = await _setup(hass, _client())
    registry = er.async_get(hass)
    rows = er.async_entries_for_config_entry(registry, entry.entry_id)
    unique_ids = [e.unique_id for e in rows]

    assert len(unique_ids) == len(set(unique_ids))
    assert "SITE-TEST_OPT-TEST-1_power" in unique_ids
