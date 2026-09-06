"""Shared device info and entity base."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SolarEdgeWebCoordinator

if TYPE_CHECKING:
    from .models import InverterInfo, LiveData, OptimizerInfo, SiteSnapshot

MANUFACTURER = "SolarEdge"


def site_device_info(snapshot: SiteSnapshot) -> DeviceInfo:
    """Device info for the site itself."""
    return DeviceInfo(
        identifiers={(DOMAIN, snapshot.site_id)},
        manufacturer=MANUFACTURER,
        name="SolarEdge Site",
        model="Monitoring site",
        entry_type=None,
    )


def inverter_device_info(
    snapshot: SiteSnapshot,
    inverter: InverterInfo,
    live: LiveData | None,
) -> DeviceInfo:
    """Device info for an inverter.

    Nesting under the site is applied at registration via ``via_device_id``;
    ``DeviceInfo`` no longer carries a ``via_device`` identifier tuple.
    """
    del snapshot  # Parent site is linked by device id in ``_async_register_devices``.
    data = (live.inverters if live else {}).get(inverter.serial)
    return DeviceInfo(
        identifiers={(DOMAIN, inverter.serial)},
        manufacturer=data.manufacturer if data and data.manufacturer else MANUFACTURER,
        name=inverter.display_name,
        model=data.model if data and data.model else None,
        sw_version=data.cpu_version if data else None,
        serial_number=inverter.serial,
    )


def optimizer_device_info(
    snapshot: SiteSnapshot,
    optimizer: OptimizerInfo,
    live: LiveData | None,
) -> DeviceInfo:
    """Device info for an optimizer.

    Nesting under the inverter is applied at registration via ``via_device_id``.
    The string name is not a device; it rides along as an optimizer attribute
    on later entities.
    """
    del snapshot  # Parent inverter is linked by device id in ``_async_register_devices``.
    data = (live.optimizers if live else {}).get(optimizer.serial)
    return DeviceInfo(
        identifiers={(DOMAIN, optimizer.serial)},
        manufacturer=MANUFACTURER,
        name=f"Optimizer {optimizer.display_name}",
        model=data.model if data and data.model else None,
        serial_number=optimizer.serial,
    )


class SolarEdgeWebEntity(CoordinatorEntity[SolarEdgeWebCoordinator]):
    """Base for every entity in this integration."""

    _attr_has_entity_name = True

    @property
    def available(self) -> bool:
        """Whether this entity has data worth trusting.

        Last-known values are held through brief outages; only a sustained
        failure marks the data stale. ``UpdateFailed`` clears
        ``last_update_success`` on the first failed cycle, so
        ``CoordinatorEntity.available`` would strobe every panel entity for a
        single hiccup. Trust last-known data until ``data_is_stale``.
        """
        return self.coordinator.data is not None and not self.coordinator.data_is_stale
