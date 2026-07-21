"""Select entities for the Boiler Controller integration."""
from __future__ import annotations

from typing import List, Callable

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import DOMAIN
from .const import BOILER_MODES, BOILER_MODE_CALIBRATING


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities for this config entry."""
    controller = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    async_add_entities([BoilerControllerModeSelect(hass, config_entry, controller)])


class BoilerControllerModeSelect(SelectEntity):
    """Select entity toggling automatic/manual dimming."""

    _attr_should_poll = False
    _attr_options = BOILER_MODES
    _attr_icon = "mdi:lightning-bolt-outline"

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, controller) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.controller = controller
        self._attr_name = f"{config_entry.title} Control Mode"
        self._attr_unique_id = f"{config_entry.entry_id}_control_mode"
        self._attr_current_option = controller.control_mode
        self._remove_callbacks: List[Callable[[], None]] = []

    async def async_added_to_hass(self) -> None:
        self._remove_callbacks.append(
            async_dispatcher_connect(
                self.hass,
                self.controller.get_control_mode_signal(),
                self._handle_mode_update,
            )
        )
        self._remove_callbacks.append(
            async_dispatcher_connect(
                self.hass,
                self.controller.get_calibration_state_signal(),
                self._handle_calibration_state,
            )
        )
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        for remove in self._remove_callbacks:
            remove()
        self._remove_callbacks.clear()

    @callback
    def _handle_mode_update(self, mode: str) -> None:
        self._attr_current_option = mode
        self.async_write_ha_state()

    @callback
    def _handle_calibration_state(self, active: bool) -> None:
        if active:
            self._attr_current_option = BOILER_MODE_CALIBRATING
        else:
            self._attr_current_option = self.controller.control_mode
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        if self.controller.is_calibration_active or option == BOILER_MODE_CALIBRATING:
            raise HomeAssistantError("Cannot change mode while calibration is running")
        await self.controller.async_set_control_mode(option)

    @property
    def available(self) -> bool:
        return super().available and not self.controller.is_calibration_active

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.config_entry.entry_id)},
            "name": self.config_entry.title,
            "manufacturer": "Powerbaas",
            "model": "Boiler Controller",
            "sw_version": self.controller.device_firmware_version,
        }
