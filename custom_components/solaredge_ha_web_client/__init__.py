"""The SolarEdge Web Client integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import PLATFORMS
from .coordinator import SolarEdgeWebConfigEntry, SolarEdgeWebCoordinator
from .entity import inverter_device_info, optimizer_device_info, site_device_info


async def async_setup_entry(hass: HomeAssistant, entry: SolarEdgeWebConfigEntry) -> bool:
    """Set up a SolarEdge site from a config entry."""
    coordinator = SolarEdgeWebCoordinator(hass, entry)
    try:
        await coordinator.async_load_snapshot()
    except UpdateFailed as err:
        raise ConfigEntryNotReady(str(err)) from err
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    _async_register_devices(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SolarEdgeWebConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: SolarEdgeWebConfigEntry) -> None:
    """Reload when the options change, so a new interval takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_devices(
    hass: HomeAssistant,
    entry: SolarEdgeWebConfigEntry,
    coordinator: SolarEdgeWebCoordinator,
) -> None:
    """Register site, inverters and optimizers up front.

    Registering here rather than letting entities imply devices means the
    hierarchy exists even for equipment whose entities are all disabled by
    default. Home Assistant now parents devices by ``via_device_id``, not by
    an identifier tuple.
    """
    registry = dr.async_get(hass)
    snapshot = coordinator.snapshot

    site = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        **site_device_info(snapshot),
    )
    inverter_ids: dict[str, str] = {}
    for inverter in snapshot.inverters:
        info = inverter_device_info(snapshot, inverter, coordinator.data)
        info["via_device_id"] = site.id
        device = registry.async_get_or_create(config_entry_id=entry.entry_id, **info)
        inverter_ids[inverter.serial] = device.id
    for optimizer in snapshot.optimizers:
        info = optimizer_device_info(snapshot, optimizer, coordinator.data)
        if parent_id := inverter_ids.get(optimizer.inverter_serial):
            info["via_device_id"] = parent_id
        registry.async_get_or_create(config_entry_id=entry.entry_id, **info)
