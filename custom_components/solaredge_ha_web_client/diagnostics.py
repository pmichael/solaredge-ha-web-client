"""Diagnostics support."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_SITE_ID

if TYPE_CHECKING:
    from .coordinator import SolarEdgeWebConfigEntry, SolarEdgeWebCoordinator
    from .models import SiteSnapshot

_MANIFEST_VERSION = json.loads(
    (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
)["version"]


def _snapshot_diagnostics(snapshot: SiteSnapshot) -> dict[str, Any]:
    return {
        "inverter_count": len(snapshot.inverters),
        "optimizer_count": len(snapshot.optimizers),
        "timezone": snapshot.timezone,
        "peak_power_kwp": snapshot.peak_power_kwp,
        "has_meter": snapshot.has_meter,
        "has_storage": snapshot.has_storage,
        "string_count": len({opt.string_name for opt in snapshot.optimizers}),
    }


def _coordinator_health(coordinator: SolarEdgeWebCoordinator) -> dict[str, Any]:
    return {
        "consecutive_failures": coordinator.consecutive_failures,
        "data_is_stale": coordinator.data_is_stale,
        "update_interval_seconds": (
            coordinator.update_interval.total_seconds() if coordinator.update_interval else None
        ),
    }


def _scrub_reason(reason: str | None, entry: SolarEdgeWebConfigEntry) -> str | None:
    if reason is None:
        return None
    scrubbed = reason
    for secret in (
        entry.data.get(CONF_SITE_ID),
        entry.data.get(CONF_USERNAME),
        entry.data.get(CONF_PASSWORD),
    ):
        if secret:
            scrubbed = scrubbed.replace(str(secret), "[redacted]")
    return scrubbed


def _entry_diagnostics(entry: SolarEdgeWebConfigEntry) -> dict[str, Any]:
    return {
        "entry_state": str(entry.state),
        "reason": _scrub_reason(getattr(entry, "reason", None), entry),
        "options": dict(entry.options),
        "version": _MANIFEST_VERSION,
    }


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: SolarEdgeWebConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Reports counts and flags rather than payloads. Serials, site IDs and
    credentials are identifying. Timezone is included because naive
    timestamps cannot be debugged without it. String names are a count only.
    """
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return {"ready": False, **_entry_diagnostics(entry)}

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
        "ready": True,
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
