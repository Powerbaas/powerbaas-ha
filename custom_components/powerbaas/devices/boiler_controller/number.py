"""Number entities for controlling manual brightness."""
from __future__ import annotations

from typing import Callable, List

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import DOMAIN
from .const import MAX_EXPORT_WATTS, BOILER_MODE_MANUAL


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities for this config entry."""
    controller = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    async_add_entities([BoilerControllerManualBrightnessNumber(hass, config_entry, controller)])


class BoilerControllerManualBrightnessNumber(NumberEntity):
    """Number entity exposing manual brightness override."""

    _attr_should_poll = False
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_EXPORT_WATTS
    _attr_native_step = 10
    _attr_native_unit_of_measurement = "W"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, controller) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.controller = controller
        self._attr_name = f"{config_entry.title} Manual Power"
        self._attr_unique_id = f"{config_entry.entry_id}_manual_watts"
        self._attr_native_value = controller.manual_watts
        self._remove_callbacks: List[Callable[[], None]] = []

    async def async_added_to_hass(self) -> None:
        self._remove_callbacks.append(
            async_dispatcher_connect(
                self.hass,
                self.controller.get_manual_watts_signal(),
                self._handle_manual_watts_update,
            )
        )
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
        self.async_write_ha_state()

    @callback
    def _handle_manual_watts_update(self, value: int) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        if self.controller.is_calibration_active:
            raise HomeAssistantError("Cannot change manual power during calibration")
        await self.controller.async_set_manual_watts(int(value))

    @callback
    def _handle_calibration_state(self, *_: object) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return (
            super().available
            and not self.controller.is_calibration_active
            and self.controller.control_mode == BOILER_MODE_MANUAL
        )

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.config_entry.entry_id)},
            "name": self.config_entry.title,
            "manufacturer": "Powerbaas",
            "model": "Boiler Controller",
            "sw_version": self.controller.device_firmware_version,
        }
