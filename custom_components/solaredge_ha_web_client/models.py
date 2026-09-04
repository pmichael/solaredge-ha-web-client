"""Typed views over the SolarEdge layout and live payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .const import LOGGER

if TYPE_CHECKING:
    from solaredge_web import InverterData, LivePower, OptimizerData


@dataclass(frozen=True, slots=True)
class InverterInfo:
    """A single inverter, as the layout describes it."""

    serial: str
    display_name: str


@dataclass(frozen=True, slots=True)
class OptimizerInfo:
    """A single optimizer and the equipment it hangs off."""

    serial: str
    display_name: str
    inverter_serial: str
    string_name: str


@dataclass(frozen=True, slots=True)
class SiteSnapshot:
    """Static facts about the site, read once per config entry at setup.

    `timezone` is load-bearing rather than decorative: the library returns
    naive site-local timestamps, so statistics cannot be placed on a timeline
    without it.
    """

    site_id: str
    peak_power_kwp: float | None
    timezone: str
    has_meter: bool
    has_storage: bool
    inverters: tuple[InverterInfo, ...]
    optimizers: tuple[OptimizerInfo, ...]

    def optimizer(self, serial: str) -> OptimizerInfo | None:
        """Look up an optimizer by serial."""
        return next((o for o in self.optimizers if o.serial == serial), None)

    def display_names_by_serial(self) -> dict[str, str]:
        """Map every device id to its layout display name.

        Statistics are keyed on position, but the energy payload is keyed on
        serial, so the import needs this translation.
        """
        return {
            **{inv.serial: inv.display_name for inv in self.inverters},
            **{opt.serial: opt.display_name for opt in self.optimizers},
        }


@dataclass(frozen=True, slots=True)
class LiveData:
    """One live poll's results.

    A cycle hits several endpoints and one failing must not discard the others,
    so each section carries its own success flag. An entity whose section failed
    reports unknown while its neighbours keep publishing.
    """

    optimizers: dict[str, OptimizerData] = field(default_factory=dict)
    temperatures: dict[str, float] = field(default_factory=dict)
    inverters: dict[str, InverterData] = field(default_factory=dict)
    live_power: LivePower | None = None
    alert_count: int | None = None
    last_success: datetime | None = None
    optimizers_ok: bool = False
    temperatures_ok: bool = False
    inverters_ok: bool = False
    live_power_ok: bool = False
    alerts_ok: bool = False

    @property
    def any_ok(self) -> bool:
        """True when at least one endpoint answered."""
        return any(
            (
                self.optimizers_ok,
                self.temperatures_ok,
                self.inverters_ok,
                self.live_power_ok,
                self.alerts_ok,
            )
        )


def _as_float(value: Any) -> float | None:
    """Read a value as a float, or None if it is not one."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_site_snapshot(
    *,
    site_id: str,
    equipment: dict[str, dict[str, Any]],
    site_information: dict[str, Any],
    site_components: dict[str, Any],
) -> SiteSnapshot:
    """Assemble the static snapshot from three layout payloads.

    `equipment` is the flat dict `async_get_equipment()` returns, already
    filtered of retired units. Its values are the original layout nodes and
    still carry `children`, which is how the inverter/string/optimizer
    hierarchy is recovered here. Nodes reachable through `children` but absent
    from `equipment` are retired and skipped: membership in the filtered dict
    is the filter, rather than re-deriving upstream's INACTIVE rule.
    """
    timezone = site_information.get("siteTimeZone")
    if not timezone:
        msg = (
            "Site information is missing siteTimeZone; statistics timestamps "
            "cannot be resolved without it"
        )
        raise ValueError(msg)

    inverters: list[InverterInfo] = []
    optimizers: list[OptimizerInfo] = []

    def descend(node: dict[str, Any], inverter_serial: str, string_name: str) -> None:
        for child in node.get("children", []):
            child_id = _device_id(child)
            child_type = child.get("type")
            if child_type == "STRING":
                descend(child, inverter_serial, str(child.get("name", "")))
            elif child_type == "OPTIMIZER":
                if child_id and child_id in equipment:
                    optimizers.append(
                        OptimizerInfo(
                            serial=child_id,
                            display_name=_short_name(child.get("name", child_id)),
                            inverter_serial=inverter_serial,
                            string_name=string_name,
                        )
                    )
                elif child_id:
                    LOGGER.debug("Skipping retired optimizer %s", child_id)
            else:
                descend(child, inverter_serial, string_name)

    for device_id, node in equipment.items():
        if node.get("type") != "INVERTER":
            continue
        inverters.append(
            InverterInfo(
                serial=device_id,
                display_name=str(node.get("name", device_id)),
            )
        )
        descend(node, device_id, "")

    LOGGER.debug(
        "Built snapshot for site %s: %s inverters, %s optimizers",
        site_id,
        len(inverters),
        len(optimizers),
    )

    return SiteSnapshot(
        site_id=site_id,
        peak_power_kwp=_as_float(site_information.get("peakPower")),
        timezone=str(timezone),
        has_meter=bool(site_components.get("hasConsumptionAndGrid", False)),
        has_storage=bool(site_components.get("hasStorage", False)),
        inverters=tuple(inverters),
        optimizers=tuple(optimizers),
    )


def _device_id(node: dict[str, Any]) -> str | None:
    """Extract a layout node's device id, matching async_get_equipment."""
    return (
        node.get("serial")
        or node.get("properties", {}).get("identifier")
        or node.get("uuid")
    )


def _short_name(name: Any) -> str:
    """Reduce a layout name to its position token, e.g. 'Module 1.1.7' -> '1.1.7'.

    Names arrive both bare and prefixed depending on equipment kind; HA core
    takes the last space-delimited token for the same reason.
    """
    return str(name).rsplit(" ", 1)[-1]
