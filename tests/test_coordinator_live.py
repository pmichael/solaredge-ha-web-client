"""Live fetching, including the partial-failure path."""

from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest
from solaredge_web import LivePower, OptimizerData

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.solaredge_ha_web_client.const import CONF_SITE_ID, DOMAIN
from custom_components.solaredge_ha_web_client.coordinator import (
    SolarEdgeWebCoordinator,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .fixtures import SITE_COMPONENTS, SITE_ID, SITE_INFORMATION, equipment_dict


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=SITE_ID,
        title="Test Site",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "hunter2",
            CONF_SITE_ID: SITE_ID,
        },
    )


def _client(**overrides: object) -> Mock:
    """A stub SolarEdgeWeb with every method this integration calls."""
    client = Mock()
    client.async_get_equipment = AsyncMock(return_value=equipment_dict())
    client.async_get_site_information = AsyncMock(return_value=SITE_INFORMATION)
    client.async_get_site_components = AsyncMock(return_value=SITE_COMPONENTS)
    client.async_get_optimizer_data = AsyncMock(
        return_value={"OPT-TEST-1": OptimizerData(serial="OPT-TEST-1", power=198.0)}
    )
    client.async_get_optimizer_temperatures = AsyncMock(
        return_value={"OPT-TEST-1": 41.5}
    )
    client.async_get_inverter_data = AsyncMock(return_value={})
    client.async_get_live_power = AsyncMock(
        return_value=LivePower(
            current_power=4210.0,
            max_power=11700.0,
            is_communicating=True,
            last_update_time=None,
        )
    )
    client.async_get_alerts = AsyncMock(
        return_value={"totalAlertsCount": 0, "topAlerts": []}
    )
    for name, value in overrides.items():
        setattr(client, name, value)
    return client


async def _coordinator(hass: HomeAssistant, client: Mock) -> SolarEdgeWebCoordinator:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.solaredge_ha_web_client.coordinator.SolarEdgeWeb",
        return_value=client,
    ):
        coordinator = SolarEdgeWebCoordinator(hass, entry)
    await coordinator.async_load_snapshot()
    return coordinator


async def test_successful_cycle_populates_every_section(hass: HomeAssistant) -> None:
    coordinator = await _coordinator(hass, _client())
    data = await coordinator._async_update_data()

    assert data.optimizers["OPT-TEST-1"].power == 198.0
    assert data.temperatures["OPT-TEST-1"] == 41.5
    assert data.live_power is not None
    assert data.alert_count == 0
    assert data.last_success is not None
    assert data.optimizers_ok
    assert data.temperatures_ok
    assert data.live_power_ok
    assert data.alerts_ok


async def test_one_failed_endpoint_does_not_discard_the_others(
    hass: HomeAssistant,
) -> None:
    """A temperature outage must not blank out working power sensors."""
    client = _client(
        async_get_optimizer_temperatures=AsyncMock(
            side_effect=aiohttp.ClientError("boom")
        )
    )
    coordinator = await _coordinator(hass, client)
    data = await coordinator._async_update_data()

    assert data.optimizers_ok is True
    assert data.optimizers["OPT-TEST-1"].power == 198.0
    assert data.temperatures_ok is False
    assert data.temperatures == {}


async def test_total_failure_raises_update_failed(hass: HomeAssistant) -> None:
    """If nothing answered there is no data, and the coordinator must say so."""
    error = AsyncMock(side_effect=aiohttp.ClientError("boom"))
    client = _client(
        async_get_optimizer_data=error,
        async_get_optimizer_temperatures=error,
        async_get_inverter_data=error,
        async_get_live_power=error,
        async_get_alerts=error,
    )
    coordinator = await _coordinator(hass, client)
    with pytest.raises(Exception, match="SolarEdge"):
        await coordinator._async_update_data()


async def test_credential_rejection_propagates_immediately(
    hass: HomeAssistant,
) -> None:
    """Reauth must not wait for the other endpoints to fail too."""
    client = _client(
        async_get_optimizer_data=AsyncMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=Mock(), history=(), status=401, message="denied"
            )
        )
    )
    coordinator = await _coordinator(hass, client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_snapshot_is_loaded_once(hass: HomeAssistant) -> None:
    """Static layout must not be refetched on every poll."""
    client = _client()
    coordinator = await _coordinator(hass, client)
    await coordinator._async_update_data()
    await coordinator._async_update_data()
    assert client.async_get_site_information.await_count == 1


async def test_requests_are_spaced(hass: HomeAssistant) -> None:
    """Politeness on an API with no published limits and no support channel."""
    with patch(
        "custom_components.solaredge_ha_web_client.coordinator.asyncio.sleep"
    ) as sleep:
        coordinator = await _coordinator(hass, _client())
        await coordinator._async_update_data()
    assert sleep.await_count >= 4
