import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, CONF_DEVICE_TYPE, DEVICE_TYPE_P1_METER, DEVICE_TYPE_BOILER_CONTROLLER
from .devices import p1_meter, boiler_controller

_LOGGER = logging.getLogger(__name__)

PLATFORMS_BY_DEVICE_TYPE = {
    DEVICE_TYPE_P1_METER: ["sensor"],
    DEVICE_TYPE_BOILER_CONTROLLER: ["sensor", "select", "number", "button"],
}

_SETUP_ENTRY = {
    DEVICE_TYPE_P1_METER: p1_meter.async_setup_entry,
    DEVICE_TYPE_BOILER_CONTROLLER: boiler_controller.async_setup_entry,
}
_UNLOAD_ENTRY = {
    DEVICE_TYPE_P1_METER: p1_meter.async_unload_entry,
    DEVICE_TYPE_BOILER_CONTROLLER: boiler_controller.async_unload_entry,
}


def _device_type(entry: ConfigEntry) -> str:
    # Entries created before the Boiler Controller was added have no
    # device_type stored yet - they are always P1 meters.
    return entry.data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_P1_METER)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an old config entry to the current version."""
    if _device_type(entry) == DEVICE_TYPE_P1_METER and entry.version == 1:
        p1_meter.migrate_legacy_entities(hass, entry)
        hass.config_entries.async_update_entry(entry, version=2)
        _LOGGER.info("Powerbaas entry %s migrated to version 2", entry.entry_id)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    device_type = _device_type(entry)
    setup_entry = _SETUP_ENTRY.get(device_type)
    if setup_entry is None:
        _LOGGER.error("Unknown Powerbaas device type: %s", device_type)
        return False

    device_data = await setup_entry(hass, entry)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "device_type": device_type,
        **device_data,
    }

    await hass.config_entries.async_forward_entry_setups(
        entry, PLATFORMS_BY_DEVICE_TYPE[device_type]
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    device_type = _device_type(entry)
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS_BY_DEVICE_TYPE[device_type]
    )

    if unload_ok:
        unload_entry = _UNLOAD_ENTRY.get(device_type)
        if unload_entry is not None:
            await unload_entry(hass, entry)
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    return unload_ok
