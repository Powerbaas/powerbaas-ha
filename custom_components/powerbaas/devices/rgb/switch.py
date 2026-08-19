"""Switch entity for Powerbaas RGB color-blind mode."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN


def _device_info(coordinator, entry: ConfigEntry) -> DeviceInfo:
    system = (coordinator.data or {}).get("system") or {}
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=coordinator.device_name,
        manufacturer="Powerbaas",
        model="Powerbaas RGB",
        sw_version=str(system.get("firmwareVersion", "Unknown")),
        configuration_url=coordinator.device_url,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([RgbColorBlindSwitch(coordinator, entry)])


class RgbColorBlindSwitch(CoordinatorEntity, SwitchEntity):
    """Toggle the ring's color-blind palette (used in meter-follow modes)."""

    _attr_has_entity_name = True
    _attr_name = "Color Blind"
    _attr_icon = "mdi:eye-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_color_blind"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def available(self) -> bool:
        return self.coordinator.device_online

    @property
    def is_on(self) -> bool:
        rgb = (self.coordinator.data or {}).get("rgb") or {}
        return bool(rgb.get("colorBlind"))

    async def async_turn_on(self, **kwargs) -> None:
        if not await self.coordinator.client.async_set_rgb(colorBlind=1):
            raise HomeAssistantError("Failed to enable color-blind mode on the Powerbaas RGB")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        if not await self.coordinator.client.async_set_rgb(colorBlind=0):
            raise HomeAssistantError("Failed to disable color-blind mode on the Powerbaas RGB")
        await self.coordinator.async_request_refresh()
