"""Switch platform entry point - routes to the device-specific implementation."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEVICE_TYPE_RGB
from .devices.boiler_controller import switch as boiler_controller_switch
from .devices.rgb import switch as rgb_switch


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device_type = hass.data[DOMAIN][entry.entry_id]["device_type"]
    if device_type == DEVICE_TYPE_RGB:
        await rgb_switch.async_setup_entry(hass, entry, async_add_entities)
    else:
        await boiler_controller_switch.async_setup_entry(hass, entry, async_add_entities)
