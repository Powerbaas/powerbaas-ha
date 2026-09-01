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
        # Bumped on every command; lets _apply_optimistic_update() detect
        # and drop a stale response from an older, superseded command.
        self._command_seq = 0

    @property
    def available(self) -> bool:
        return self.coordinator.device_online

    @property
    def is_on(self) -> bool:
        rgb = (self.coordinator.data or {}).get("rgb") or {}
        return bool(rgb.get("colorBlind"))

    async def async_turn_on(self, **kwargs) -> None:
        self._command_seq += 1
        seq = self._command_seq
        if not await self.coordinator.client.async_set_rgb(colorBlind=1):
            raise HomeAssistantError("Failed to enable color-blind mode on the Powerbaas RGB")
        self._apply_optimistic_update({"colorBlind": True}, seq)

    async def async_turn_off(self, **kwargs) -> None:
        self._command_seq += 1
        seq = self._command_seq
        if not await self.coordinator.client.async_set_rgb(colorBlind=0):
            raise HomeAssistantError("Failed to disable color-blind mode on the Powerbaas RGB")
        self._apply_optimistic_update({"colorBlind": False}, seq)

    def _apply_optimistic_update(self, rgb_update: dict, seq: int) -> None:
        """Merge a just-applied command into coordinator data immediately.

        A refresh right after sending a command can race the firmware's own
        apply latency and read back the pre-command state, which flashes the
        entity back to the old value until the next scheduled poll corrects
        it. Updating the coordinator's cached data directly avoids that
        round trip; the next scheduled poll still reconciles with the device.

        A call whose sequence number has been superseded by a later one
        (e.g. its response arrived after a newer command's) skips applying
        its update, so it can't clobber the newer, already-applied value.
        """
        if seq != self._command_seq:
            return
        data = dict(self.coordinator.data or {})
        data["rgb"] = {**(data.get("rgb") or {}), **rgb_update}
        self.coordinator.async_set_updated_data(data)
