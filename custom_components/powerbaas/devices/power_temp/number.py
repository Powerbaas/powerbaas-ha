"""Number entities for the Powerbaas PowerTemp (alarm thresholds)."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import DOMAIN
from .const import CONFIG_NUMBERS
from .entity import PowerTempConfigEntity, async_apply


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        PowerTempConfigNumber(
            coordinator,
            entry,
            name=name,
            path=path,
            min_value=min_value,
            max_value=max_value,
            step=step,
            icon=icon,
            unique_suffix=unique_suffix,
        )
        for name, path, min_value, max_value, step, icon, unique_suffix in CONFIG_NUMBERS
    )


class PowerTempConfigNumber(PowerTempConfigEntity, NumberEntity):
    """A threshold from /api/config.

    Cross-field rules (alarm above warning, ...) are enforced by the
    firmware; a rejected value surfaces as an error in the UI.
    """

    # Mixes absolute limits with deltas (hysteresis, ambient delta), so no
    # temperature device_class: HA's °F conversion would treat a delta as an
    # absolute temperature.
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        *,
        name: str,
        path: list[str],
        min_value: float,
        max_value: float,
        step: float,
        icon: str,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator, entry, path, unique_suffix)
        self._attr_name = name
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_icon = icon

    @property
    def native_value(self) -> float | None:
        value = self._config_value
        return value if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        await async_apply(self.coordinator, self.coordinator.async_update_config(self._body(value)))
