"""Diagnostics support."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from .coordinator import SolarEdgeWebConfigEntry, SolarEdgeWebCoordinator
    from .models import SiteSnapshot


def _snapshot_diagnostics(snapshot: SiteSnapshot) -> dict[str, Any]:
    return {
        "inverter_count": len(snapshot.inverters),
        "optimizer_count": len(snapshot.optimizers),
        "timezone": snapshot.timezone,
        "peak_power_kwp": snapshot.peak_power_kwp,
        "has_meter": snapshot.has_meter,
        "has_storage": snapshot.has_storage,
        "strings": sorted({opt.string_name for opt in snapshot.optimizers}),
    }


def _coordinator_health(coordinator: SolarEdgeWebCoordinator) -> dict[str, Any]:
    return {
        "consecutive_failures": coordinator.consecutive_failures,
        "data_is_stale": coordinator.data_is_stale,
        "update_interval_seconds": (
            coordinator.update_interval.total_seconds() if coordinator.update_interval else None
        ),
    }


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: SolarEdgeWebConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Reports counts and flags rather than payloads. Serials, site IDs and
    credentials are all identifying, and a diagnostics dump is something users
    paste into public issue trackers — so this reports the shape of the data,
    which is what actually helps debugging, and none of its identifiers.
    """
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return {"ready": False}

    snapshot = coordinator.snapshot
    health = _coordinator_health(coordinator)
    live = coordinator.data

    if live is None:
        return {
            "ready": True,
            "snapshot": _snapshot_diagnostics(snapshot),
            "live": None,
            **health,
        }

    return {
        "snapshot": _snapshot_diagnostics(snapshot),
        "live": {
            "optimizers_ok": live.optimizers_ok,
            "temperatures_ok": live.temperatures_ok,
            "inverters_ok": live.inverters_ok,
            "live_power_ok": live.live_power_ok,
            "alerts_ok": live.alerts_ok,
            "optimizer_readings": len(live.optimizers),
            "temperature_readings": len(live.temperatures),
            "inverter_readings": len(live.inverters),
            "alert_count": live.alert_count,
            "last_success": live.last_success.isoformat() if live.last_success else None,
        },
        **health,
    }
