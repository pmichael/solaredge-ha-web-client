"""Statistic identifiers, timezone handling and bucketing."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from solaredge_web import EnergyData

from custom_components.solaredge_ha_web_client.models import (
    InverterInfo,
    SiteSnapshot,
    build_site_snapshot,
)
from custom_components.solaredge_ha_web_client.statistics import (
    bucket_energy,
    reference_statistic_id,
    resolve_site_timezone,
    statistic_id_for,
)

from .fixtures import SITE_COMPONENTS, SITE_ID, SITE_INFORMATION, equipment_dict


def _snapshot() -> SiteSnapshot:
    return build_site_snapshot(
        site_id=SITE_ID,
        equipment=equipment_dict(),
        site_information=SITE_INFORMATION,
        site_components=SITE_COMPONENTS,
    )


def test_statistic_id_uses_position_not_serial() -> None:
    """A replaced optimizer keeps its position, so history stays continuous."""
    assert (
        statistic_id_for(SITE_ID, "opt", "1.1.7") == "solaredge_ha_web_client:site_test_opt_1_1_7"
    )


def test_statistic_id_slugifies_the_site() -> None:
    assert statistic_id_for("My Site!", "inv", "Inverter 1").startswith(
        "solaredge_ha_web_client:my_site_inv_"
    )


def test_statistic_id_is_stable() -> None:
    """Statistic IDs are a persistent contract; drift orphans history."""
    assert statistic_id_for(SITE_ID, "opt", "1.1.1") == statistic_id_for(SITE_ID, "opt", "1.1.1")


async def test_resolves_the_site_timezone_not_the_ha_one(
    hass: HomeAssistant,
) -> None:
    """Core attaches HA's timezone here, which is wrong for a site abroad."""
    hass.config.time_zone = "UTC"
    snapshot = build_site_snapshot(
        site_id=SITE_ID,
        equipment=equipment_dict(),
        site_information={**SITE_INFORMATION, "siteTimeZone": "America/Los_Angeles"},
        site_components=SITE_COMPONENTS,
    )
    tzinfo = await resolve_site_timezone(hass, snapshot)
    assert tzinfo == ZoneInfo("America/Los_Angeles")


async def test_unknown_timezone_raises(hass: HomeAssistant) -> None:
    snapshot = build_site_snapshot(
        site_id=SITE_ID,
        equipment=equipment_dict(),
        site_information={**SITE_INFORMATION, "siteTimeZone": "Mars/Olympus"},
        site_components=SITE_COMPONENTS,
    )
    with pytest.raises(ValueError, match="Mars/Olympus"):
        await resolve_site_timezone(hass, snapshot)


def test_buckets_are_site_local_converted_to_utc() -> None:
    """A naive 08:00 is tagged with the site offset, not converted to UTC."""
    tzinfo = ZoneInfo("Asia/Jerusalem")
    energy = [
        EnergyData(
            start_time=datetime(2026, 9, 4, 8, 0),
            values={"OPT-TEST-1": 420.0},
        )
    ]
    buckets = bucket_energy(energy, _snapshot(), tzinfo)
    key = statistic_id_for(SITE_ID, "opt", "1.1.1")

    start, value = buckets[key][0]
    assert value == 420.0
    assert start.utcoffset().total_seconds() == 3 * 3600
    assert start.hour == 8


def test_absent_serial_counts_as_zero_for_that_hour() -> None:
    """No report means no energy, which for a running sum is zero, not a gap."""
    tzinfo = ZoneInfo("Asia/Jerusalem")
    energy = [EnergyData(start_time=datetime(2026, 9, 4, 8, 0), values={"OPT-TEST-1": 420.0})]
    buckets = bucket_energy(energy, _snapshot(), tzinfo)
    key = statistic_id_for(SITE_ID, "opt", "1.1.2")

    assert buckets[key][0][1] == 0.0


def test_unknown_serial_is_skipped_not_imported(caplog: pytest.LogCaptureFixture) -> None:
    """A serial absent from the layout is a hardware change, not a data point."""
    tzinfo = ZoneInfo("Asia/Jerusalem")
    energy = [
        EnergyData(
            start_time=datetime(2026, 9, 4, 8, 0),
            values={"OPT-TEST-1": 420.0, "OPT-UNKNOWN": 999.0},
        )
    ]
    buckets = bucket_energy(energy, _snapshot(), tzinfo)

    assert not any("unknown" in key for key in buckets)
    assert "OPT-UNKNOWN" in caplog.text


def test_buckets_are_time_ordered() -> None:
    """Cumulative sums are only correct if applied in order."""
    tzinfo = ZoneInfo("Asia/Jerusalem")
    energy = [
        EnergyData(start_time=datetime(2026, 9, 4, 9, 0), values={"OPT-TEST-1": 2.0}),
        EnergyData(start_time=datetime(2026, 9, 4, 8, 0), values={"OPT-TEST-1": 1.0}),
    ]
    buckets = bucket_energy(energy, _snapshot(), tzinfo)
    key = statistic_id_for(SITE_ID, "opt", "1.1.1")

    starts = [start for start, _ in buckets[key]]
    assert starts == sorted(starts)


def test_inverters_get_their_own_series() -> None:
    tzinfo = ZoneInfo("Asia/Jerusalem")
    energy = [EnergyData(start_time=datetime(2026, 9, 4, 8, 0), values={"INV-TEST-1": 800.0})]
    buckets = bucket_energy(energy, _snapshot(), tzinfo)
    key = statistic_id_for(SITE_ID, "inv", "1")

    assert buckets[key][0][1] == 800.0


def test_reference_statistic_id_matches_a_bucket_key() -> None:
    """If these drift, the gate always fires and we never see why."""
    snapshot = _snapshot()
    tzinfo = ZoneInfo("Asia/Jerusalem")
    energy = [EnergyData(start_time=datetime(2026, 9, 4, 8, 0), values={"OPT-TEST-1": 1.0})]
    reference = reference_statistic_id(snapshot)
    assert reference is not None
    assert reference in bucket_energy(energy, snapshot, tzinfo)


def test_reference_statistic_id_uses_inverter_when_no_optimizers() -> None:
    snapshot = SiteSnapshot(
        site_id=SITE_ID,
        peak_power_kwp=11.7,
        timezone="Asia/Jerusalem",
        has_meter=False,
        has_storage=False,
        inverters=(InverterInfo(serial="INV-TEST-1", display_name="Inverter 1"),),
        optimizers=(),
    )
    assert reference_statistic_id(snapshot) == statistic_id_for(SITE_ID, "inv", "1")
