"""Select entities for the Boiler Controller integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN
from .const import (
    BOILER_MODES,
    BOILER_MODE_CALIBRATING,
    MAX_HEATING_WATTS_OPTIONS,
)


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
    """Set up select entities for this config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    async_add_entities([
        BoilerControllerModeSelect(coordinator, config_entry),
        BoilerControllerMaxHeatingWattsSelect(coordinator, config_entry),
    ])


class BoilerControllerModeSelect(CoordinatorEntity, SelectEntity):
    """Select entity toggling automatic/manual dimming."""

    _attr_should_poll = False
    _attr_options = BOILER_MODES
    _attr_icon = "mdi:lightning-bolt-outline"

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self._attr_name = f"{config_entry.title} Control Mode"
        self._attr_unique_id = f"{config_entry.entry_id}_control_mode"

    @property
    def current_option(self) -> str:
        data = self.coordinator.data or {}
        if data.get("calibration_active"):
            return BOILER_MODE_CALIBRATING
        return data.get("control_mode")

    async def async_select_option(self, option: str) -> None:
        data = self.coordinator.data or {}
        if data.get("calibration_active") or option == BOILER_MODE_CALIBRATING:
            raise HomeAssistantError("Cannot change mode while calibration is running")
        await self.coordinator.async_set_control_mode(option)

    @property
    def available(self) -> bool:
        data = self.coordinator.data or {}
        return self.coordinator.device_online and not data.get("calibration_active")

    @property
    def device_info(self) -> dict[str, Any]:
        return _device_info(self.coordinator, self.config_entry)


class BoilerControllerMaxHeatingWattsSelect(CoordinatorEntity, SelectEntity):
    """Select entity for the configurable max heating wattage safety ceiling."""

    _attr_should_poll = False
    _attr_options = [str(w) for w in MAX_HEATING_WATTS_OPTIONS]
    _attr_icon = "mdi:flash-alert"

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self._attr_name = f"{config_entry.title} Max Heating Power"
        self._attr_unique_id = f"{config_entry.entry_id}_max_heating_watts"

    @property
    def current_option(self) -> str:
        return str((self.coordinator.data or {}).get("max_heating_watts"))

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_max_heating_watts(int(option))

    @property
    def available(self) -> bool:
        return self.coordinator.device_online

    @property
    def device_info(self) -> dict[str, Any]:
        return _device_info(self.coordinator, self.config_entry)
