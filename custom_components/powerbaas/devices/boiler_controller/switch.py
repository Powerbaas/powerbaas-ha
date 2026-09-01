"""Switch entities for the Boiler Controller integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN


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
    """Set up switch entities for this config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    async_add_entities([BoilerControllerSsrSwitch(coordinator, config_entry)])


class BoilerControllerSsrSwitch(CoordinatorEntity, SwitchEntity):
    """Switch entity controlling the BC module's SSR relay (on/off)."""

    _attr_should_poll = False
    _attr_icon = "mdi:electric-switch"

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self._attr_name = f"{config_entry.title} SSR"
        self._attr_unique_id = f"{config_entry.entry_id}_ssr"

    def _ssr_on(self) -> bool | None:
        status = (self.coordinator.data or {}).get("status") or {}
        on = (status.get("ssr") or {}).get("on")
        return bool(on) if on is not None else None

    @property
    def is_on(self) -> bool | None:
        return self._ssr_on()

    @property
    def available(self) -> bool:
        return self.coordinator.device_online and self._ssr_on() is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_ssr(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_ssr(False)

    @property
    def device_info(self) -> dict[str, Any]:
        return _device_info(self.coordinator, self.config_entry)
