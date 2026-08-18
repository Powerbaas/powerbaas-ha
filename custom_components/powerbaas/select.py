"""Select platform entry point - routes to the device-specific implementation."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEVICE_TYPE_AIRCO_BRIDGE, DEVICE_TYPE_RGB
from .devices.boiler_controller import select as boiler_controller_select
from .devices.airco_bridge import select as airco_bridge_select
from .devices.rgb import select as rgb_select


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device_type = hass.data[DOMAIN][entry.entry_id]["device_type"]
    if device_type == DEVICE_TYPE_AIRCO_BRIDGE:
        await airco_bridge_select.async_setup_entry(hass, entry, async_add_entities)
    elif device_type == DEVICE_TYPE_RGB:
        await rgb_select.async_setup_entry(hass, entry, async_add_entities)
    else:
        await boiler_controller_select.async_setup_entry(hass, entry, async_add_entities)
