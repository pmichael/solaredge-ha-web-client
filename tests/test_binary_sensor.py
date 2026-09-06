"""Binary sensor entities."""

from unittest.mock import AsyncMock

import aiohttp
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from solaredge_web import InverterData

from .test_coordinator_live import _client
from .test_init import _setup


async def test_no_alerts_is_off(hass: HomeAssistant) -> None:
    await _setup(hass, _client())
    state = hass.states.get("binary_sensor.solaredge_site_site_test_alerts")
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes["device_class"] == BinarySensorDeviceClass.PROBLEM


async def test_open_alerts_is_on_and_carries_detail(hass: HomeAssistant) -> None:
    client = _client(
        async_get_alerts=AsyncMock(
            return_value={
                "totalAlertsCount": 2,
                "topAlerts": [{"name": "Panel underperforming"}],
            }
        )
    )
    await _setup(hass, client)
    state = hass.states.get("binary_sensor.solaredge_site_site_test_alerts")
    assert state.state == STATE_ON
    assert state.attributes["alert_count"] == 2


async def test_failed_alert_fetch_is_unknown_not_off(hass: HomeAssistant) -> None:
    """Reporting 'no problem' when we do not know is the dangerous failure."""
    client = _client(async_get_alerts=AsyncMock(side_effect=aiohttp.ClientError("boom")))
    await _setup(hass, client)
    state = hass.states.get("binary_sensor.solaredge_site_site_test_alerts")
    assert state.state == STATE_UNKNOWN


async def test_inverter_connectivity_follows_status(hass: HomeAssistant) -> None:
    client = _client(
        async_get_inverter_data=AsyncMock(
            return_value={"INV-TEST-1": InverterData(serial="INV-TEST-1", status="ACTIVE")}
        )
    )
    await _setup(hass, client)
    state = hass.states.get("binary_sensor.inverter_1_connectivity")
    assert state is not None
    assert state.state == STATE_ON


async def test_inverter_connectivity_off_when_not_active(
    hass: HomeAssistant,
) -> None:
    client = _client(
        async_get_inverter_data=AsyncMock(
            return_value={"INV-TEST-1": InverterData(serial="INV-TEST-1", status="DISABLED")}
        )
    )
    await _setup(hass, client)
    assert hass.states.get("binary_sensor.inverter_1_connectivity").state == STATE_OFF
