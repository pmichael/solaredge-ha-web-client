"""Statistics gating and its error boundary."""

from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest
from homeassistant.components.recorder import Recorder
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.util import dt as dt_util

from custom_components.solaredge_ha_web_client.const import STATISTICS_INTERVAL

from .test_coordinator_live import _client, _coordinator


@pytest.fixture
def mock_recorder_before_hass(recorder_db_url: str) -> None:
    """Create the recorder DB URL before hass starts.

    pytest-asyncio otherwise constructs hass first, which trips
    recorder_db_url's ``assert not hass_fixture_setup``.
    """


async def test_imports_when_no_statistics_exist(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """A fresh install must backfill rather than wait twelve hours."""
    client = _client(async_get_energy_data=AsyncMock(return_value=[]))
    coordinator = await _coordinator(hass, client)

    with (
        patch(
            "custom_components.solaredge_ha_web_client.coordinator.async_import_energy",
            new=AsyncMock(return_value=3),
        ) as import_energy,
        patch(
            "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
            new=AsyncMock(return_value=None),
        ),
    ):
        await coordinator._async_update_data()

    import_energy.assert_awaited_once()


async def test_skips_when_statistics_are_recent(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    client = _client(async_get_energy_data=AsyncMock(return_value=[]))
    coordinator = await _coordinator(hass, client)
    recent = dt_util.utcnow() - timedelta(hours=1)

    with (
        patch(
            "custom_components.solaredge_ha_web_client.coordinator.async_import_energy",
            new=AsyncMock(return_value=0),
        ) as import_energy,
        patch(
            "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
            new=AsyncMock(return_value=recent),
        ),
    ):
        await coordinator._async_update_data()

    import_energy.assert_not_awaited()


async def test_imports_once_the_interval_has_elapsed(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    client = _client(async_get_energy_data=AsyncMock(return_value=[]))
    coordinator = await _coordinator(hass, client)
    stale = dt_util.utcnow() - STATISTICS_INTERVAL - timedelta(minutes=1)

    with (
        patch(
            "custom_components.solaredge_ha_web_client.coordinator.async_import_energy",
            new=AsyncMock(return_value=3),
        ) as import_energy,
        patch(
            "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
            new=AsyncMock(return_value=stale),
        ),
    ):
        await coordinator._async_update_data()

    import_energy.assert_awaited_once()


async def test_statistics_failure_does_not_fail_the_cycle(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """Live sensors must survive a broken history import."""
    client = _client(async_get_energy_data=AsyncMock(side_effect=aiohttp.ClientError("boom")))
    coordinator = await _coordinator(hass, client)

    with patch(
        "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
        new=AsyncMock(return_value=None),
    ):
        data = await coordinator._async_update_data()

    assert data.optimizers["OPT-TEST-1"].power == 198.0
    assert coordinator.consecutive_failures == 0


async def test_soft_statistics_failure_does_not_refetch_every_cycle(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """A transport failure must back off like an empty payload, not retry every poll."""
    energy = AsyncMock(side_effect=aiohttp.ClientError("boom"))
    client = _client(async_get_energy_data=energy)
    coordinator = await _coordinator(hass, client)

    with patch(
        "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
        new=AsyncMock(return_value=None),
    ):
        first = await coordinator._async_update_data()
        second = await coordinator._async_update_data()

    assert first.optimizers["OPT-TEST-1"].power == 198.0
    assert second.optimizers["OPT-TEST-1"].power == 198.0
    assert coordinator.consecutive_failures == 0
    assert energy.await_count == 1


async def test_statistics_failure_does_not_trigger_reauth_alone(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """A 401 on the energy endpoint is still a credential problem."""
    client = _client(
        async_get_energy_data=AsyncMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=Mock(), history=(), status=401, message="denied"
            )
        )
    )
    coordinator = await _coordinator(hass, client)

    with (
        patch(
            "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await coordinator._async_update_data()


async def test_statistics_403_triggers_reauth(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    """A 403 on the energy endpoint is a credential problem, same as 401."""
    client = _client(
        async_get_energy_data=AsyncMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=Mock(), history=(), status=403, message="denied"
            )
        )
    )
    coordinator = await _coordinator(hass, client)

    with (
        patch(
            "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await coordinator._async_update_data()


async def test_empty_energy_payload_does_not_refetch_every_cycle(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """An empty history response must not turn the 12-hour gate into every poll."""
    energy = AsyncMock(return_value=[])
    client = _client(async_get_energy_data=energy)
    coordinator = await _coordinator(hass, client)

    with patch(
        "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
        new=AsyncMock(return_value=None),
    ):
        await coordinator._async_update_data()
        await coordinator._async_update_data()

    assert energy.await_count == 1


async def test_statistics_value_error_is_not_a_soft_failure(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """A ValueError is a caller bug and must not be swallowed."""
    client = _client(async_get_energy_data=AsyncMock(side_effect=ValueError("bad resolution")))
    coordinator = await _coordinator(hass, client)

    with (
        patch(
            "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(ValueError, match="bad resolution"),
    ):
        await coordinator._async_update_data()
