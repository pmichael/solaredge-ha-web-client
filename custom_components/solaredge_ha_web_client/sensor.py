"""Sensor platform."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .coordinator import SolarEdgeWebCoordinator
from .entity import (
    SolarEdgeWebEntity,
    inverter_device_info,
    optimizer_device_info,
    site_device_info,
)
from .models import InverterInfo, LiveData, OptimizerInfo, SiteSnapshot

if TYPE_CHECKING:
    from .coordinator import SolarEdgeWebConfigEntry

type SensorValue = StateType | date | datetime | Decimal


@dataclass(frozen=True, kw_only=True)
class OptimizerSensorDescription(SensorEntityDescription):
    """Describes an optimizer sensor."""

    value_fn: Callable[[LiveData, str], SensorValue]
    section_ok_fn: Callable[[LiveData], bool]


@dataclass(frozen=True, kw_only=True)
class InverterSensorDescription(SensorEntityDescription):
    """Describes an inverter sensor."""

    value_fn: Callable[[LiveData, str], SensorValue]
    section_ok_fn: Callable[[LiveData], bool]


@dataclass(frozen=True, kw_only=True)
class SiteSensorDescription(SensorEntityDescription):
    """Describes a site sensor."""

    value_fn: Callable[[LiveData, SiteSnapshot], SensorValue]
    section_ok_fn: Callable[[LiveData], bool]


OPTIMIZER_SENSORS: tuple[OptimizerSensorDescription, ...] = (
    OptimizerSensorDescription(
        key="power",
        translation_key="power",
        name="Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda live, serial: getattr(live.optimizers.get(serial), "power", None),
        section_ok_fn=lambda live: live.optimizers_ok,
    ),
    OptimizerSensorDescription(
        key="max_temperature_today",
        translation_key="max_temperature_today",
        # Named a maximum because the endpoint returns the highest reading over
        # a date range, not an instantaneous one. It resets at local midnight.
        name="Max temperature today",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda live, serial: live.temperatures.get(serial),
        section_ok_fn=lambda live: live.temperatures_ok,
    ),
    OptimizerSensorDescription(
        key="module_voltage",
        translation_key="module_voltage",
        name="Module voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda live, serial: getattr(live.optimizers.get(serial), "voltage", None),
        section_ok_fn=lambda live: live.optimizers_ok,
    ),
    OptimizerSensorDescription(
        key="optimizer_voltage",
        translation_key="optimizer_voltage",
        name="Optimizer voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda live, serial: getattr(
            live.optimizers.get(serial), "optimizer_voltage", None
        ),
        section_ok_fn=lambda live: live.optimizers_ok,
    ),
    OptimizerSensorDescription(
        key="current",
        translation_key="current",
        name="Current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda live, serial: getattr(live.optimizers.get(serial), "current", None),
        section_ok_fn=lambda live: live.optimizers_ok,
    ),
    OptimizerSensorDescription(
        key="last_measurement",
        translation_key="last_measurement",
        name="Last measurement",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda live, serial: getattr(
            live.optimizers.get(serial), "last_measurement", None
        ),
        section_ok_fn=lambda live: live.optimizers_ok,
    ),
)

INVERTER_SENSORS: tuple[InverterSensorDescription, ...] = (
    InverterSensorDescription(
        key="ac_power_cloud",
        translation_key="ac_power_cloud",
        # "(Cloud)" distinguishes this from the Modbus sensor of the same
        # meaning, which is local, faster, and will disagree by minutes.
        name="AC power (Cloud)",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda live, serial: getattr(live.inverters.get(serial), "power", None),
        section_ok_fn=lambda live: live.inverters_ok,
    ),
    InverterSensorDescription(
        key="status_cloud",
        translation_key="status_cloud",
        name="Status (Cloud)",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda live, serial: getattr(live.inverters.get(serial), "status", None),
        section_ok_fn=lambda live: live.inverters_ok,
    ),
)

SITE_SENSORS: tuple[SiteSensorDescription, ...] = (
    SiteSensorDescription(
        key="site_power_cloud",
        translation_key="site_power_cloud",
        name="Site power (Cloud)",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda live, _snapshot: getattr(live.live_power, "current_power", None),
        section_ok_fn=lambda live: live.live_power_ok,
    ),
    SiteSensorDescription(
        key="peak_power",
        translation_key="peak_power",
        name="Peak power",
        # Deliberately no device class and no state class: kWp is a nameplate
        # rating, not a measurement, and no HA device class accepts the unit.
        native_unit_of_measurement="kWp",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda _live, snapshot: snapshot.peak_power_kwp,
        section_ok_fn=lambda _live: True,
    ),
    SiteSensorDescription(
        key="last_successful_update",
        translation_key="last_successful_update",
        name="Last successful update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda live, _snapshot: live.last_success,
        section_ok_fn=lambda _live: True,
    ),
    SiteSensorDescription(
        key="alert_count",
        translation_key="alert_count",
        name="Open alerts",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda live, _snapshot: live.alert_count,
        section_ok_fn=lambda live: live.alerts_ok,
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: SolarEdgeWebConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    snapshot = coordinator.snapshot

    entities: list[SensorEntity] = [
        SolarEdgeSiteSensor(coordinator, description) for description in SITE_SENSORS
    ]
    entities += [
        SolarEdgeInverterSensor(coordinator, inverter, description)
        for inverter in snapshot.inverters
        for description in INVERTER_SENSORS
    ]
    entities += [
        SolarEdgeOptimizerSensor(coordinator, optimizer, description)
        for optimizer in snapshot.optimizers
        for description in OPTIMIZER_SENSORS
    ]
    async_add_entities(entities)


class SolarEdgeOptimizerSensor(SolarEdgeWebEntity, SensorEntity):
    """A sensor for one optimizer."""

    entity_description: OptimizerSensorDescription

    def __init__(
        self,
        coordinator: SolarEdgeWebCoordinator,
        optimizer: OptimizerInfo,
        description: OptimizerSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._optimizer = optimizer
        self._attr_unique_id = (
            f"{coordinator.snapshot.site_id}_{optimizer.serial}_{description.key}"
        )
        self._attr_device_info = optimizer_device_info(
            coordinator.snapshot, optimizer, coordinator.data
        )
        self._attr_extra_state_attributes = {
            "string": optimizer.string_name,
            "position": optimizer.display_name,
        }

    @property
    def native_value(self) -> SensorValue:
        """Return the reading, or None when its section failed this cycle."""
        live = self.coordinator.data
        if live is None or not self.entity_description.section_ok_fn(live):
            return None
        value = self.entity_description.value_fn(live, self._optimizer.serial)
        if isinstance(value, datetime) and value.tzinfo is None:
            timezone = self.coordinator.snapshot.timezone
            zone = dt_util.get_time_zone(timezone)
            if zone is None:
                msg = f"SolarEdge reported an unknown site timezone: {timezone}"
                raise ValueError(msg)
            return value.replace(tzinfo=zone)
        return value


class SolarEdgeInverterSensor(SolarEdgeWebEntity, SensorEntity):
    """A sensor for one inverter."""

    entity_description: InverterSensorDescription

    def __init__(
        self,
        coordinator: SolarEdgeWebCoordinator,
        inverter: InverterInfo,
        description: InverterSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._inverter = inverter
        self._attr_unique_id = f"{coordinator.snapshot.site_id}_{inverter.serial}_{description.key}"
        self._attr_device_info = inverter_device_info(
            coordinator.snapshot, inverter, coordinator.data
        )

    @property
    def native_value(self) -> SensorValue:
        """Return the reading, or None when its section failed this cycle."""
        live = self.coordinator.data
        if live is None or not self.entity_description.section_ok_fn(live):
            return None
        return self.entity_description.value_fn(live, self._inverter.serial)


class SolarEdgeSiteSensor(SolarEdgeWebEntity, SensorEntity):
    """A site-level sensor."""

    entity_description: SiteSensorDescription

    def __init__(
        self,
        coordinator: SolarEdgeWebCoordinator,
        description: SiteSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.snapshot.site_id}_{description.key}"
        self._attr_device_info = site_device_info(coordinator.snapshot)

    @property
    def native_value(self) -> SensorValue:
        """Return the reading, or None when its section failed this cycle."""
        live = self.coordinator.data
        if live is None or not self.entity_description.section_ok_fn(live):
            return None
        return self.entity_description.value_fn(live, self.coordinator.snapshot)

    @property
    def available(self) -> bool:
        """Peak power and last-update stay available; they are not live reads."""
        if self.entity_description.key in ("peak_power", "last_successful_update"):
            return True
        return super().available
