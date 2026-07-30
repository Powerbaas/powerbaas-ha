"""Switch entities for the Boiler Controller integration."""
from __future__ import annotations

from typing import Any, Callable, List

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities for this config entry."""
    controller = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    async_add_entities([BoilerControllerSsrSwitch(hass, config_entry, controller)])


class BoilerControllerSsrSwitch(SwitchEntity):
    """Switch entity controlling the BC module's SSR relay (on/off)."""

    _attr_should_poll = False
    _attr_icon = "mdi:electric-switch"

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, controller) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.controller = controller
        self._attr_name = f"{config_entry.title} SSR"
        self._attr_unique_id = f"{config_entry.entry_id}_ssr"
        self._attr_is_on = None
        self._attr_available = False
        self._remove_callbacks: List[Callable[[], None]] = []

    async def async_added_to_hass(self) -> None:
        self._remove_callbacks.append(
            async_dispatcher_connect(
                self.hass,
                self.controller.get_device_status_signal(),
                self._handle_status_update,
            )
        )
        self._refresh_from_status(self.controller.get_device_status())
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        for remove in self._remove_callbacks:
            remove()
        self._remove_callbacks.clear()

    @callback
    def _handle_status_update(self, status) -> None:
        self._refresh_from_status(status)
        self.async_write_ha_state()

    def _refresh_from_status(self, status) -> None:
        if not status:
            self._attr_available = False
            return
        on = (status.get("ssr") or {}).get("on")
        self._attr_available = on is not None
        if on is not None:
            self._attr_is_on = bool(on)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.controller.async_set_ssr(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.controller.async_set_ssr(False)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.config_entry.entry_id)},
            "name": self.config_entry.title,
            "manufacturer": "Powerbaas",
            "model": "Boiler Controller",
            "sw_version": self.controller.device_firmware_version,
            "configuration_url": self.controller.device_url,
        }
