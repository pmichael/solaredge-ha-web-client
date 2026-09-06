"""Statistics gating and its error boundary."""

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest
from homeassistant.components.recorder import Recorder
from homeassistant.core import HomeAssistant
from homeassistant.helpers.recorder import get_instance
from homeassistant.util import dt as dt_util
from solaredge_web import EnergyData

from custom_components.solaredge_ha_web_client.const import (
    STATISTICS_INTERVAL,
    STATISTICS_OVERLAP,
)
from custom_components.solaredge_ha_web_client.coordinator import (
    _async_newest_statistic_time,
)
from custom_components.solaredge_ha_web_client.models import InverterInfo
from custom_components.solaredge_ha_web_client.statistics import (
    async_import_energy,
    reference_statistic_id,
)

from .test_coordinator_live import _client, _coordinator


async def _run_update(hass: HomeAssistant, coordinator: object) -> object:
    data = await coordinator._async_update_data()
    await hass.async_block_till_done()
    return data


async def _wait_for_recorder(hass: HomeAssistant) -> None:
    await hass.async_block_till_done()
    await get_instance(hass).async_block_till_done()


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
        await _run_update(hass, coordinator)

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
        await _run_update(hass, coordinator)

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
        await _run_update(hass, coordinator)

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
        data = await _run_update(hass, coordinator)

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
        first = await _run_update(hass, coordinator)
        second = await _run_update(hass, coordinator)

    assert first.optimizers["OPT-TEST-1"].power == 198.0
    assert second.optimizers["OPT-TEST-1"].power == 198.0
    assert coordinator.consecutive_failures == 0
    assert energy.await_count == 1


async def test_recorder_due_check_failure_does_not_start_backoff(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """A failed freshness check is not an energy attempt; retry next cycle."""
    energy = AsyncMock(return_value=[])
    client = _client(async_get_energy_data=energy)
    coordinator = await _coordinator(hass, client)

    with patch(
        "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
        new=AsyncMock(side_effect=[RuntimeError("recorder down"), None]),
    ):
        first = await _run_update(hass, coordinator)
        second = await _run_update(hass, coordinator)

    assert first.optimizers["OPT-TEST-1"].power == 198.0
    assert second.optimizers["OPT-TEST-1"].power == 198.0
    assert coordinator.consecutive_failures == 0
    assert energy.await_count == 1


async def test_statistics_401_still_triggers_reauth(
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
        patch.object(coordinator.config_entry, "async_start_reauth") as start_reauth,
    ):
        data = await _run_update(hass, coordinator)

    assert data.optimizers["OPT-TEST-1"].power == 198.0
    start_reauth.assert_called_once_with(hass)


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
        patch.object(coordinator.config_entry, "async_start_reauth") as start_reauth,
    ):
        data = await _run_update(hass, coordinator)

    assert data.optimizers["OPT-TEST-1"].power == 198.0
    start_reauth.assert_called_once_with(hass)


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
        await _run_update(hass, coordinator)
        await _run_update(hass, coordinator)

    assert energy.await_count == 1


async def test_statistics_value_error_is_not_a_soft_failure(
    recorder_mock: Recorder, hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A ValueError is a caller bug: live stays up and the attempt is not stamped."""
    client = _client(async_get_energy_data=AsyncMock(side_effect=ValueError("bad resolution")))
    coordinator = await _coordinator(hass, client)

    with patch(
        "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
        new=AsyncMock(return_value=None),
    ):
        data = await _run_update(hass, coordinator)

    assert data.optimizers["OPT-TEST-1"].power == 198.0
    assert coordinator.consecutive_failures == 0
    assert coordinator._last_statistics_attempt is None
    assert "caller bug" in caplog.text
    assert "bad resolution" in caplog.text


async def test_optimizer_less_site_imports_inverter_statistics(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """Sites without optimizers still have inverter energy history."""
    energy = AsyncMock(return_value=[])
    coordinator = await _coordinator(hass, _client(async_get_energy_data=energy))
    coordinator._snapshot = replace(
        coordinator.snapshot,
        optimizers=(),
        inverters=(InverterInfo(serial="INV-TEST-1", display_name="Inverter 1"),),
    )

    with patch(
        "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
        new=AsyncMock(return_value=None),
    ):
        await _run_update(hass, coordinator)

    assert energy.await_count == 1


async def test_unmocked_gate_skips_when_recorder_has_a_recent_row(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """The recorder row, not a mock, must decide whether an import is due."""
    energy = AsyncMock(return_value=[])
    coordinator = await _coordinator(hass, _client(async_get_energy_data=energy))
    reference = reference_statistic_id(coordinator.snapshot)
    assert reference is not None

    now = dt_util.utcnow()
    site_hour = datetime(now.year, now.month, now.day, now.hour)
    payload = [EnergyData(start_time=site_hour, values={"OPT-TEST-1": 100.0})]
    written = await async_import_energy(hass, coordinator.snapshot, "Test Site", payload)
    assert written >= 1
    await _wait_for_recorder(hass)

    newest = await _async_newest_statistic_time(hass, reference)
    assert newest is not None
    due, stored = await coordinator._async_statistics_are_due()
    assert due is False
    assert stored == newest

    await _run_update(hass, coordinator)
    assert energy.await_count == 0


async def test_unmocked_gate_imports_when_recorder_row_is_stale(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    energy = AsyncMock(return_value=[])
    coordinator = await _coordinator(hass, _client(async_get_energy_data=energy))
    assert reference_statistic_id(coordinator.snapshot) is not None

    stale_utc = dt_util.utcnow() - STATISTICS_INTERVAL - timedelta(hours=1)
    site_tz = await dt_util.async_get_time_zone(coordinator.snapshot.timezone)
    assert site_tz is not None
    site_hour = stale_utc.astimezone(site_tz).replace(
        tzinfo=None, minute=0, second=0, microsecond=0
    )
    payload = [EnergyData(start_time=site_hour, values={"OPT-TEST-1": 100.0})]
    written = await async_import_energy(hass, coordinator.snapshot, "Test Site", payload)
    assert written >= 1
    await _wait_for_recorder(hass)

    due, stored = await coordinator._async_statistics_are_due()
    assert due is True
    assert stored is not None

    await _run_update(hass, coordinator)
    assert energy.await_count == 1


async def test_subsequent_import_passes_overlap_window(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    newest = dt_util.utcnow() - STATISTICS_INTERVAL - timedelta(hours=1)
    energy = AsyncMock(return_value=[])
    coordinator = await _coordinator(hass, _client(async_get_energy_data=energy))

    with patch(
        "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
        new=AsyncMock(return_value=newest),
    ):
        await _run_update(hass, coordinator)

    energy.assert_awaited_once()
    kwargs = energy.await_args.kwargs
    assert kwargs["start_date"] == newest - STATISTICS_OVERLAP
    assert "end_date" in kwargs


async def test_skips_import_when_recorder_is_absent(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    energy = AsyncMock(return_value=[])
    coordinator = await _coordinator(hass, _client(async_get_energy_data=energy))

    await _run_update(hass, coordinator)
    await _run_update(hass, coordinator)

    assert energy.await_count == 0
    recorder_logs = [r.message for r in caplog.records if "recorder" in r.message.lower()]
    assert len(recorder_logs) == 1


async def test_live_cycle_returns_before_energy_import_finishes(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """A hung history fetch must not delay live sensors."""
    release = asyncio.Event()

    async def _slow_energy(**_kwargs: object) -> list[object]:
        await release.wait()
        return []

    energy = AsyncMock(side_effect=_slow_energy)
    coordinator = await _coordinator(hass, _client(async_get_energy_data=energy))

    with patch(
        "custom_components.solaredge_ha_web_client.coordinator._async_newest_statistic_time",
        new=AsyncMock(return_value=None),
    ):
        data = await asyncio.wait_for(coordinator._async_update_data(), timeout=2)
        assert data.optimizers["OPT-TEST-1"].power == 198.0
        release.set()
        await hass.async_block_till_done()

    assert energy.await_count == 1
