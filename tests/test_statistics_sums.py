"""Cumulative sums. The highest-risk logic in the integration."""

from datetime import datetime
from unittest.mock import patch

import pytest
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.core import HomeAssistant
from solaredge_web import EnergyData

from custom_components.solaredge_ha_web_client.models import build_site_snapshot
from custom_components.solaredge_ha_web_client.statistics import (
    async_import_energy,
    statistic_id_for,
)

from .fixtures import SITE_COMPONENTS, SITE_ID, SITE_INFORMATION, equipment_dict


@pytest.fixture
def mock_recorder_before_hass(recorder_db_url: str) -> None:
    """Create the recorder DB URL before hass starts.

    pytest-asyncio otherwise constructs hass first, which trips
    recorder_db_url's ``assert not hass_fixture_setup``.
    """


def _snapshot() -> object:
    return build_site_snapshot(
        site_id=SITE_ID,
        equipment=equipment_dict(),
        site_information=SITE_INFORMATION,
        site_components=SITE_COMPONENTS,
    )


def _energy(hours: list[tuple[int, float]]) -> list[EnergyData]:
    return [
        EnergyData(start_time=datetime(2026, 9, 4, hour, 0), values={"OPT-TEST-1": value})
        for hour, value in hours
    ]


async def test_sums_accumulate_across_hours(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    """Sums must be a running total, not a repeat of each hourly value."""
    written: list[tuple[dict[str, object], list[dict[str, float]]]] = []
    with patch(
        "custom_components.solaredge_ha_web_client.statistics.async_add_external_statistics",
        side_effect=lambda _hass, meta, stats: written.append((meta, stats)),
    ):
        await async_import_energy(
            hass, _snapshot(), "Test Site", _energy([(8, 100.0), (9, 200.0), (10, 50.0)])
        )

    key = statistic_id_for(SITE_ID, "opt", "1.1.1")
    series = next(stats for meta, stats in written if meta["statistic_id"] == key)
    sums = [row["sum"] for row in series]
    assert sums == [100.0, 300.0, 350.0]
    assert [row["state"] for row in series] == [100.0, 200.0, 50.0]


async def test_sums_continue_from_the_stored_baseline(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """Restarting must not reset a panel's lifetime total to zero."""
    written: list[tuple[dict[str, object], list[dict[str, float]]]] = []
    with (
        patch(
            "custom_components.solaredge_ha_web_client.statistics.async_add_external_statistics",
            side_effect=lambda _h, meta, stats: written.append((meta, stats)),
        ),
        patch(
            "custom_components.solaredge_ha_web_client.statistics._async_get_baselines",
            return_value={
                statistic_id_for(SITE_ID, "opt", "1.1.1"): 5000.0,
                statistic_id_for(SITE_ID, "opt", "1.1.2"): 0.0,
                statistic_id_for(SITE_ID, "inv", "1"): 0.0,
            },
        ),
    ):
        await async_import_energy(hass, _snapshot(), "Test Site", _energy([(8, 100.0), (9, 200.0)]))

    key = statistic_id_for(SITE_ID, "opt", "1.1.1")
    series = next(stats for meta, stats in written if meta["statistic_id"] == key)
    sums = [row["sum"] for row in series]
    assert sums == [5100.0, 5300.0]


async def test_reimporting_the_same_hours_does_not_double_count(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """Overlapping windows are normal; they must overwrite, not accumulate."""
    calls: list[tuple[dict[str, object], list[dict[str, float]]]] = []
    with (
        patch(
            "custom_components.solaredge_ha_web_client.statistics.async_add_external_statistics",
            side_effect=lambda _h, meta, stats: calls.append((meta, stats)),
        ),
        patch(
            "custom_components.solaredge_ha_web_client.statistics._async_get_baselines",
            return_value={
                statistic_id_for(SITE_ID, "opt", "1.1.1"): 0.0,
                statistic_id_for(SITE_ID, "opt", "1.1.2"): 0.0,
                statistic_id_for(SITE_ID, "inv", "1"): 0.0,
            },
        ),
    ):
        payload = _energy([(8, 100.0), (9, 200.0)])
        await async_import_energy(hass, _snapshot(), "Test Site", payload)
        await async_import_energy(hass, _snapshot(), "Test Site", payload)

    key = statistic_id_for(SITE_ID, "opt", "1.1.1")
    series = [stats for meta, stats in calls if meta["statistic_id"] == key]
    assert [row["sum"] for row in series[0]] == [100.0, 300.0]
    assert [row["sum"] for row in series[1]] == [100.0, 300.0]


async def test_metadata_declares_no_mean(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    """An hourly energy total has no meaningful mean, and we supply none."""
    metadata: list[dict[str, object]] = []
    with patch(
        "custom_components.solaredge_ha_web_client.statistics.async_add_external_statistics",
        side_effect=lambda _h, meta, _s: metadata.append(meta),
    ):
        await async_import_energy(hass, _snapshot(), "Test Site", _energy([(8, 1.0)]))

    assert metadata[0]["mean_type"] is StatisticMeanType.NONE
    assert metadata[0]["has_sum"] is True
    assert metadata[0]["unit_of_measurement"] == "Wh"
    assert metadata[0]["source"] == "solaredge_ha_web_client"


async def test_empty_payload_writes_nothing(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    """An empty response is a failed fetch, not a day of zeros."""
    with patch(
        "custom_components.solaredge_ha_web_client.statistics.async_add_external_statistics"
    ) as add:
        written = await async_import_energy(hass, _snapshot(), "Test Site", [])

    assert written == 0
    add.assert_not_called()


async def test_every_series_is_written(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    """Two optimizers and one inverter."""
    with patch(
        "custom_components.solaredge_ha_web_client.statistics.async_add_external_statistics"
    ) as add:
        written = await async_import_energy(hass, _snapshot(), "Test Site", _energy([(8, 1.0)]))

    assert written == 3
    assert add.call_count == 3
