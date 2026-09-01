"""Select entity for the Powerbaas RGB application mode."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN
from .const import APPLICATION_MODES


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
    async_add_entities([RgbModeSelect(coordinator, entry)])


class RgbModeSelect(CoordinatorEntity, SelectEntity):
    """Pick Powerbaas, HomeWizard or Standalone application mode."""

    _attr_has_entity_name = True
    _attr_name = "Application Mode"
    _attr_icon = "mdi:tune"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(APPLICATION_MODES)

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_application_mode"
        self._attr_device_info = _device_info(coordinator, entry)
        # Bumped on every command; lets async_select_option() detect and
        # drop a stale response from an older, superseded command.
        self._command_seq = 0

    @property
    def available(self) -> bool:
        return self.coordinator.device_online

    @property
    def current_option(self) -> str | None:
        system = (self.coordinator.data or {}).get("system") or {}
        mode = system.get("mode")
        if mode in APPLICATION_MODES:
            return mode
        return None

    async def async_select_option(self, option: str) -> None:
        if option not in APPLICATION_MODES:
            raise HomeAssistantError(f"Unknown Powerbaas RGB mode: {option}")
        self._command_seq += 1
        seq = self._command_seq
        if not await self.coordinator.client.async_set_mode(option):
            raise HomeAssistantError("Failed to set application mode on the Powerbaas RGB")
        # A refresh right after sending a command can race the firmware's
        # own apply latency and read back the pre-command mode, which
        # flashes the entity back to the old value until the next scheduled
        # poll corrects it. Updating the coordinator's cached data directly
        # avoids that round trip; the next scheduled poll still reconciles
        # with the device. A call superseded by a later one (its response
        # arrived after a newer command's) skips applying, so it can't
        # clobber the newer, already-applied value.
        if seq != self._command_seq:
            return
        data = dict(self.coordinator.data or {})
        data["system"] = {**(data.get("system") or {}), "mode": option}
        self.coordinator.async_set_updated_data(data)
