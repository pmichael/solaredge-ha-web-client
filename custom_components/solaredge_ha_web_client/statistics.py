"""Long-term statistics import for per-module energy history."""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.recorder import get_instance
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify
from homeassistant.util.unit_conversion import EnergyConverter

from .const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from solaredge_web import EnergyData

    from .models import SiteSnapshot


def statistic_id_for(site_id: str, kind: str, display_name: str) -> str:
    """Build a statistic ID keyed on equipment position.

    Position rather than serial: a replaced optimizer reports a new serial but
    keeps its position, and serial-keyed history would split in two at exactly
    the moment continuous history matters most.
    """
    return f"{DOMAIN}:{slugify(site_id)}_{kind}_{slugify(display_name)}"


async def resolve_site_timezone(
    hass: HomeAssistant,  # noqa: ARG001 — HA timezone helper; zone is the site's
    snapshot: SiteSnapshot,
) -> tzinfo:
    """Resolve the site's IANA timezone name to a tzinfo.

    The site's own timezone, never Home Assistant's. The library documents
    energy timestamps as naive site-local, so using the local timezone would
    shift every imported hour for a site in another zone.
    """
    resolved = await dt_util.async_get_time_zone(snapshot.timezone)
    if resolved is None:
        msg = f"SolarEdge reported an unknown site timezone: {snapshot.timezone}"
        raise ValueError(msg)
    return resolved


def bucket_energy(
    energy_data: list[EnergyData],
    snapshot: SiteSnapshot,
    site_tz: tzinfo,
) -> dict[str, list[tuple[datetime, float]]]:
    """Turn serial-keyed hourly energy into statistic-ID-keyed ordered series.

    Every known optimizer and inverter gets an entry for every hour in the
    payload. An hour a device did not report is zero rather than absent: for a
    running sum, "no production" and "no data" both mean the total did not move,
    and leaving a gap would make the next cumulative value look like a spike.
    """
    kinds = {
        **{
            inv.serial: ("inv", str(inv.display_name).rsplit(" ", 1)[-1])
            for inv in snapshot.inverters
        },
        **{opt.serial: ("opt", opt.display_name) for opt in snapshot.optimizers},
    }
    buckets: dict[str, list[tuple[datetime, float]]] = {
        statistic_id_for(snapshot.site_id, kind, name): [] for kind, name in kinds.values()
    }

    unknown: set[str] = set()
    for entry in sorted(energy_data, key=lambda e: e.start_time):
        start = entry.start_time.replace(tzinfo=site_tz)
        for serial in entry.values:
            if serial not in kinds:
                unknown.add(serial)
        for serial, (kind, name) in kinds.items():
            key = statistic_id_for(snapshot.site_id, kind, name)
            buckets[key].append((start, float(entry.values.get(serial, 0.0))))

    if unknown:
        LOGGER.info(
            "Skipping %s equipment id(s) present in the energy data but absent "
            "from the site layout; this is expected after a hardware change: %s",
            len(unknown),
            ", ".join(sorted(unknown)),
        )

    return buckets


async def async_import_energy(
    hass: HomeAssistant,
    snapshot: SiteSnapshot,
    entry_title: str,
    energy_data: list[EnergyData],
) -> int:
    """Import hourly energy history as external statistics.

    Returns the number of series written.
    """
    if not energy_data:
        LOGGER.warning(
            "SolarEdge returned no energy data for site %s; skipping import",
            snapshot.site_id,
        )
        return 0

    site_tz = await resolve_site_timezone(hass, snapshot)
    buckets = bucket_energy(energy_data, snapshot, site_tz)
    if not buckets:
        return 0

    window_start = min(rows[0][0] for rows in buckets.values() if rows)
    baselines = await _async_get_baselines(hass, set(buckets), window_start)

    names = _display_names(snapshot)
    written = 0
    for statistic_id, rows in buckets.items():
        if not rows:
            continue
        running = baselines.get(statistic_id, 0.0)
        statistics: list[StatisticData] = []
        for start, value in rows:
            running += value
            statistics.append(StatisticData(start=start, state=value, sum=running))

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{entry_title} {names.get(statistic_id, statistic_id)}",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class=EnergyConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        )
        LOGGER.debug("Writing %s statistics for %s", len(statistics), statistic_id)
        async_add_external_statistics(hass, metadata, statistics)
        written += 1

    return written


def _display_names(snapshot: SiteSnapshot) -> dict[str, str]:
    """Map statistic ID back to a human-readable equipment name."""
    names: dict[str, str] = {}
    for inv in snapshot.inverters:
        token = str(inv.display_name).rsplit(" ", 1)[-1]
        names[statistic_id_for(snapshot.site_id, "inv", token)] = f"Inverter {token}"
    for opt in snapshot.optimizers:
        names[statistic_id_for(snapshot.site_id, "opt", opt.display_name)] = (
            f"Module {opt.display_name}"
        )
    return names


async def _async_get_baselines(
    hass: HomeAssistant,
    statistic_ids: set[str],
    window_start: datetime,
) -> dict[str, float]:
    """Read the cumulative sum standing immediately before the import window.

    Ported from HA core's solaredge coordinator, which solves this against the
    same endpoints. Two lookups: the hour before the window, then a fallback to
    the newest statistic on record, accepted only if it predates the window.
    Without the fallback, an integration offline longer than the fetched window
    would restart every panel's total from zero.
    """
    before = window_start - timedelta(hours=1)
    recorder = get_instance(hass)

    during = await recorder.async_add_executor_job(
        statistics_during_period,
        hass,
        before,
        before + timedelta(seconds=1),
        statistic_ids,
        "hour",
        None,
        {"sum"},
    )

    baselines: dict[str, float] = {}
    for statistic_id in statistic_ids:
        rows = during.get(statistic_id)
        if rows:
            baselines[statistic_id] = float(rows[0]["sum"] or 0.0)
            continue

        last = await recorder.async_add_executor_job(
            get_last_statistics,
            hass,
            1,
            statistic_id,
            True,  # noqa: FBT003 — convert_units is positional on HA's helper
            {"sum"},
        )
        candidate = last.get(statistic_id) if last else None
        if candidate and candidate[0]["start"] < window_start.timestamp():
            baselines[statistic_id] = float(candidate[0]["sum"] or 0.0)
        else:
            # New install, or statistics cleared from developer tools.
            baselines[statistic_id] = 0.0

    return baselines
