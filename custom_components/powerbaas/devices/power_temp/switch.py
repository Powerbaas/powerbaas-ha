"""Switch entities for the PowerTemp."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import DOMAIN
from .entity import PowerTempConfigEntity, async_apply


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([PowerTempDeltaSwitch(coordinator, entry)])


class PowerTempDeltaSwitch(PowerTempConfigEntity, SwitchEntity):
    """Use warning/alarm limits relative to the ambient sensor (delta.enabled)."""

    _attr_name = "Ambient Delta Limits"
    _attr_icon = "mdi:delta"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, ["delta", "enabled"], "delta_enabled")

    @property
    def is_on(self) -> bool | None:
        value = self._config_value
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await async_apply(self.coordinator, self.coordinator.async_update_config(self._body(True)))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await async_apply(self.coordinator, self.coordinator.async_update_config(self._body(False)))
