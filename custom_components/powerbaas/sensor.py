"""Sensor platform entry point - routes to the device-specific implementation."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEVICE_TYPE_BOILER_CONTROLLER
from .devices.p1_meter import sensor as p1_meter_sensor
from .devices.boiler_controller import sensor as boiler_controller_sensor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device_type = hass.data[DOMAIN][entry.entry_id]["device_type"]
    if device_type == DEVICE_TYPE_BOILER_CONTROLLER:
        await boiler_controller_sensor.async_setup_entry(hass, entry, async_add_entities)
    else:
        await p1_meter_sensor.async_setup_entry(hass, entry, async_add_entities)
