"""Long-term statistics import for per-module energy history."""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

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
