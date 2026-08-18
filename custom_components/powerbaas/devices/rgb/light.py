"""Light entity for the Powerbaas RGB."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN
from .const import EFFECT_SOLID, EFFECTS


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
    async_add_entities([RgbLight(coordinator, entry)])


class RgbLight(CoordinatorEntity, LightEntity):
    """On/off, brightness, RGB color and effect for the ring.

    Color and effect are applied by the firmware only in Standalone mode;
    in Powerbaas / HomeWizard the ring follows meter power usage. On/off
    and brightness always work.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_color_mode = ColorMode.RGB
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = list(EFFECTS)

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_light"
        self._attr_device_info = _device_info(coordinator, entry)

    def _rgb(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("rgb") or {}

    @property
    def available(self) -> bool:
        return self.coordinator.device_online

    @property
    def is_on(self) -> bool:
        return bool(self._rgb().get("ison"))

    @property
    def brightness(self) -> int | None:
        value = self._rgb().get("brightness")
        if value is None:
            return None
        return int(value)

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        rgb = self._rgb()
        r, g, b = rgb.get("solidR"), rgb.get("solidG"), rgb.get("solidB")
        if r is None or g is None or b is None:
            return None
        return (int(r), int(g), int(b))

    @property
    def effect(self) -> str | None:
        rgb = self._rgb()
        if rgb.get("isSolid"):
            return EFFECT_SOLID
        return rgb.get("effect")

    async def async_turn_on(self, **kwargs: Any) -> None:
        params: dict[str, Any] = {"on": 1}
        if ATTR_BRIGHTNESS in kwargs:
            params["brightness"] = int(kwargs[ATTR_BRIGHTNESS])
        if ATTR_RGB_COLOR in kwargs:
            red, green, blue = kwargs[ATTR_RGB_COLOR]
            params["r"] = int(red)
            params["g"] = int(green)
            params["b"] = int(blue)
            params.setdefault("effect", EFFECT_SOLID)
        if ATTR_EFFECT in kwargs:
            params["effect"] = kwargs[ATTR_EFFECT]
        if not await self.coordinator.client.async_set_rgb(**params):
            raise HomeAssistantError("Failed to set the Powerbaas RGB light")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if not await self.coordinator.client.async_set_rgb(on=0):
            raise HomeAssistantError("Failed to turn off the Powerbaas RGB")
        await self.coordinator.async_request_refresh()
