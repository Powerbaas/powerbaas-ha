"""Number entities for controlling manual brightness."""
from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN
from .const import BOILER_MODE_MANUAL, BOILER_MODE_AUTO


def _device_info(coordinator, config_entry: ConfigEntry) -> dict[str, Any]:
    system = (coordinator.data or {}).get("system") or {}
    return {
        "identifiers": {(DOMAIN, config_entry.entry_id)},
        "name": config_entry.title,
        "manufacturer": "Powerbaas",
        "model": "Boiler Controller",
        "sw_version": str(system.get("firmwareVersion", "Unknown")),
        "configuration_url": coordinator.device_url,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities for this config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    async_add_entities([
        BoilerControllerManualBrightnessNumber(coordinator, config_entry),
        BoilerControllerMinHeatingWattsNumber(coordinator, config_entry),
    ])


class BoilerControllerManualBrightnessNumber(CoordinatorEntity, NumberEntity):
    """Number entity exposing manual brightness override."""

    _attr_should_poll = False
    _attr_native_min_value = 0
    _attr_native_step = 10
    _attr_native_unit_of_measurement = "W"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:flash"

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self._attr_name = f"{config_entry.title} Target Power"
        self._attr_unique_id = f"{config_entry.entry_id}_target_watts"

    @property
    def native_max_value(self) -> float:
        return (self.coordinator.data or {}).get("max_heating_watts", 0)

    @property
    def native_value(self) -> float:
        return (self.coordinator.data or {}).get("target_watts", 0)

    async def async_set_native_value(self, value: float) -> None:
        data = self.coordinator.data or {}
        if data.get("calibration_active"):
            raise HomeAssistantError("Cannot change target power during calibration")
        if data.get("control_mode") != BOILER_MODE_MANUAL:
            raise HomeAssistantError("Target Power can only be set in Manual mode")
        await self.coordinator.async_set_target_watts(int(value))

    @property
    def available(self) -> bool:
        # Always available (not gated on Manual mode): every control mode
        # keeps this field updated with the watts it last commanded, so it
        # doubles as a log of what the controller (including Auto mode) is
        # actually doing - see the auto branch in _async_update().
        data = self.coordinator.data or {}
        return self.coordinator.device_online and not data.get("calibration_active")

    @property
    def device_info(self) -> dict[str, Any]:
        return _device_info(self.coordinator, self.config_entry)


class BoilerControllerMinHeatingWattsNumber(CoordinatorEntity, NumberEntity):
    """Number entity exposing the min heating watts floor (Auto mode only)."""

    _attr_should_poll = False
    _attr_native_min_value = 0
    _attr_native_step = 10
    _attr_native_unit_of_measurement = "W"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:flash"

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self._attr_name = f"{config_entry.title} Minimum Heating Power"
        self._attr_unique_id = f"{config_entry.entry_id}_min_heating_watts"

    @property
    def native_max_value(self) -> float:
        return (self.coordinator.data or {}).get("max_heating_watts", 0)

    @property
    def native_value(self) -> float:
        return (self.coordinator.data or {}).get("min_heating_watts", 0)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_min_heating_watts(int(value))

    @property
    def available(self) -> bool:
        data = self.coordinator.data or {}
        return (
            self.coordinator.device_online
            and not data.get("calibration_active")
            and data.get("control_mode") == BOILER_MODE_AUTO
        )

    @property
    def device_info(self) -> dict[str, Any]:
        return _device_info(self.coordinator, self.config_entry)
