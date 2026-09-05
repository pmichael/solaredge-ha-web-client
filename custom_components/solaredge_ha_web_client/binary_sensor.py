"""Binary sensor platform (entities arrive in a later task)."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SolarEdgeWebConfigEntry


async def async_setup_entry(
    _hass: HomeAssistant,
    _entry: SolarEdgeWebConfigEntry,
    _async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors; real entities are added in a later task."""
