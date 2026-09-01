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
        # Bumped on every command; lets _apply_optimistic_update() detect
        # and drop a stale response from an older, superseded command.
        self._command_seq = 0

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
        # /api/rgb only reliably applies one kind of change per request -
        # combining e.g. r/g/b with effect in a single call makes the
        # firmware reload its last-stored value for one of them instead of
        # applying what was just sent (confirmed against a real ring's debug
        # log). So each kind of change goes out as its own sequential call;
        # color is sent before effect, since switching into solid mode reads
        # back whatever color was most recently stored.
        steps: list[dict[str, Any]] = [{"on": 1}]
        optimistic: dict[str, Any] = {"ison": True}

        if ATTR_BRIGHTNESS in kwargs:
            brightness = int(kwargs[ATTR_BRIGHTNESS])
            steps.append({"brightness": brightness})
            optimistic["brightness"] = brightness

        if ATTR_RGB_COLOR in kwargs:
            red, green, blue = kwargs[ATTR_RGB_COLOR]
            r, g, b = int(red), int(green), int(blue)
            steps.append({"r": r, "g": g, "b": b})
            optimistic["solidR"] = r
            optimistic["solidG"] = g
            optimistic["solidB"] = b

        effect = kwargs.get(ATTR_EFFECT)
        if effect is None and ATTR_RGB_COLOR in kwargs and not self._rgb().get("isSolid"):
            # Only switch effect when actually moving into solid mode - a
            # plain color change while already solid must not touch it.
            effect = EFFECT_SOLID
        if effect is not None:
            steps.append({"effect": effect})
            optimistic["effect"] = effect
            optimistic["isSolid"] = effect == EFFECT_SOLID

        self._command_seq += 1
        seq = self._command_seq
        for step in steps:
            if not await self.coordinator.client.async_set_rgb(**step):
                raise HomeAssistantError("Failed to set the Powerbaas RGB light")
        self._apply_optimistic_update(optimistic, seq)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._command_seq += 1
        seq = self._command_seq
        if not await self.coordinator.client.async_set_rgb(on=0):
            raise HomeAssistantError("Failed to turn off the Powerbaas RGB")
        self._apply_optimistic_update({"ison": False}, seq)

    def _apply_optimistic_update(self, rgb_update: dict[str, Any], seq: int) -> None:
        """Merge a just-applied command into coordinator data immediately.

        A refresh right after sending a command can race the firmware's own
        apply latency and read back the pre-command state, which flashes the
        entity back to the old value until the next scheduled poll corrects
        it. Updating the coordinator's cached data directly avoids that
        round trip; the next scheduled poll still reconciles with the device.

        Dragging a slider fires several turn_on calls in quick succession,
        each awaiting its own network round trip. If an older call's
        response arrives after a newer call's (e.g. the device is briefly
        slow), applying it here would clobber the newer, already-applied
        value - so a call whose sequence number has been superseded by a
        later one skips applying its update.
        """
        if seq != self._command_seq:
            return
        data = dict(self.coordinator.data or {})
        data["rgb"] = {**(data.get("rgb") or {}), **rgb_update}
        self.coordinator.async_set_updated_data(data)
