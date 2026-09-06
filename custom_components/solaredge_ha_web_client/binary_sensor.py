"""Binary sensor platform."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import SolarEdgeWebEntity, inverter_device_info, site_device_info

if TYPE_CHECKING:
    from .coordinator import SolarEdgeWebConfigEntry, SolarEdgeWebCoordinator
    from .models import InverterInfo

ACTIVE_STATUSES = {"ACTIVE", "ON_GRID", "PRODUCING"}


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: SolarEdgeWebConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [SolarEdgeAlertsBinarySensor(coordinator)]
    entities += [
        SolarEdgeInverterConnectivity(coordinator, inverter)
        for inverter in coordinator.snapshot.inverters
    ]
    async_add_entities(entities)


class SolarEdgeAlertsBinarySensor(SolarEdgeWebEntity, BinarySensorEntity):
    """Whether the site has open alerts."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "Alerts"

    def __init__(self, coordinator: SolarEdgeWebCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.snapshot.site_id}_alerts"
        self._attr_device_info = site_device_info(coordinator.snapshot)

    @property
    def is_on(self) -> bool | None:
        """True when alerts are open, None when the fetch failed.

        None rather than False on failure: reporting "no problem" when the
        answer is unknown is the one wrong answer that matters here.
        """
        live = self.coordinator.data
        if not live.alerts_ok or live.alert_count is None:
            return None
        return live.alert_count > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the count alongside the boolean."""
        return {"alert_count": self.coordinator.data.alert_count}


class SolarEdgeInverterConnectivity(SolarEdgeWebEntity, BinarySensorEntity):
    """Whether an inverter is reporting as active."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Connectivity"

    def __init__(self, coordinator: SolarEdgeWebCoordinator, inverter: InverterInfo) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._inverter = inverter
        self._attr_unique_id = f"{coordinator.snapshot.site_id}_{inverter.serial}_connectivity"
        self._attr_device_info = inverter_device_info(
            coordinator.snapshot, inverter, coordinator.data
        )

    @property
    def is_on(self) -> bool | None:
        """True when the inverter reports an active status."""
        live = self.coordinator.data
        if not live.inverters_ok:
            return None
        data = live.inverters.get(self._inverter.serial)
        if data is None or data.status is None:
            return None
        return data.status.upper() in ACTIVE_STATUSES
