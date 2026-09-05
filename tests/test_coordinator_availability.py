"""Availability hysteresis."""

from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.solaredge_ha_web_client.const import MAX_CONSECUTIVE_FAILURES

from .test_coordinator_live import _client, _coordinator


async def test_starts_healthy(hass: HomeAssistant) -> None:
    coordinator = await _coordinator(hass, _client())
    assert coordinator.consecutive_failures == 0
    assert coordinator.data_is_stale is False


async def test_two_failures_keep_entities_available(hass: HomeAssistant) -> None:
    """One SolarEdge hiccup must not blank twenty panel sensors."""
    error = AsyncMock(side_effect=aiohttp.ClientError("boom"))
    client = _client(
        async_get_optimizer_data=error,
        async_get_optimizer_temperatures=error,
        async_get_inverter_data=error,
        async_get_live_power=error,
        async_get_alerts=error,
    )
    coordinator = await _coordinator(hass, client)

    for expected in (1, 2):
        await coordinator.async_refresh()
        assert coordinator.consecutive_failures == expected
        assert coordinator.data_is_stale is False


async def test_third_failure_marks_data_stale(hass: HomeAssistant) -> None:
    error = AsyncMock(side_effect=aiohttp.ClientError("boom"))
    client = _client(
        async_get_optimizer_data=error,
        async_get_optimizer_temperatures=error,
        async_get_inverter_data=error,
        async_get_live_power=error,
        async_get_alerts=error,
    )
    coordinator = await _coordinator(hass, client)

    for _ in range(MAX_CONSECUTIVE_FAILURES):
        await coordinator.async_refresh()

    assert coordinator.consecutive_failures == MAX_CONSECUTIVE_FAILURES
    assert coordinator.data_is_stale is True


@pytest.mark.parametrize("failure_mode", ["transport", "all_sections"])
async def test_third_failure_notifies_listeners(hass: HomeAssistant, failure_mode: str) -> None:
    error = AsyncMock(side_effect=aiohttp.ClientError("boom"))
    client = _client(
        async_get_optimizer_data=error,
        async_get_optimizer_temperatures=error,
        async_get_inverter_data=error,
        async_get_live_power=error,
        async_get_alerts=error,
    )
    coordinator = await _coordinator(hass, client)
    if failure_mode == "transport":
        coordinator._async_fetch_live = AsyncMock(side_effect=UpdateFailed("boom"))
    listener = Mock()
    remove_listener = coordinator.async_add_listener(listener)

    try:
        for expected in range(1, MAX_CONSECUTIVE_FAILURES + 1):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()
            assert listener.call_count == (1 if expected == MAX_CONSECUTIVE_FAILURES else 0)
    finally:
        remove_listener()


async def test_success_resets_the_counter(hass: HomeAssistant) -> None:
    client = _client()
    coordinator = await _coordinator(hass, client)
    coordinator._consecutive_failures = 2

    await coordinator.async_refresh()

    assert coordinator.consecutive_failures == 0
    assert coordinator.data_is_stale is False


async def test_partial_success_counts_as_success(hass: HomeAssistant) -> None:
    """Some data is not an outage."""
    client = _client(
        async_get_optimizer_temperatures=AsyncMock(side_effect=aiohttp.ClientError("boom"))
    )
    coordinator = await _coordinator(hass, client)
    coordinator._consecutive_failures = 2

    await coordinator.async_refresh()

    assert coordinator.consecutive_failures == 0


async def test_value_error_is_not_an_outage(hass: HomeAssistant) -> None:
    """A library ValueError is a caller bug, not a SolarEdge hiccup."""
    client = _client(async_get_optimizer_data=AsyncMock(side_effect=ValueError("bad resolution")))
    coordinator = await _coordinator(hass, client)

    await coordinator.async_refresh()

    assert coordinator.consecutive_failures == 0
    assert coordinator.data_is_stale is False
