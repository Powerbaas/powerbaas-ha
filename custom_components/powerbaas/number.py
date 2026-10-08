"""Number platform entry point - routes to the device-specific implementation."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEVICE_TYPE_POWER_TEMP
from .devices.boiler_controller import number as boiler_controller_number
from .devices.power_temp import number as power_temp_number


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device_type = hass.data[DOMAIN][entry.entry_id]["device_type"]
    if device_type == DEVICE_TYPE_POWER_TEMP:
        await power_temp_number.async_setup_entry(hass, entry, async_add_entities)
    else:
        await boiler_controller_number.async_setup_entry(hass, entry, async_add_entities)
