"""Availability hysteresis."""

from unittest.mock import AsyncMock

import aiohttp
from homeassistant.core import HomeAssistant

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
