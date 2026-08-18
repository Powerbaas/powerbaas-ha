"""Sensor entities for the Powerbaas RGB."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN
from .const import DIAGNOSTIC_SENSORS, MAIN_SENSORS, is_valid_power_usage


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


def _read_path(data: Any, path: list[str]):
    for key in path:
        data = data.get(key) if isinstance(data, dict) else None
    return data


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[SensorEntity] = [RgbStatusSensor(coordinator, entry)]
    for name, path, unit, device_class, state_class, multiplier, entity_category, icon, unique_suffix in (
        MAIN_SENSORS + DIAGNOSTIC_SENSORS
    ):
        entities.append(
            RgbFieldSensor(
                coordinator,
                entry,
                name=name,
                path=path,
                unit=unit,
                device_class=device_class,
                state_class=state_class,
                multiplier=multiplier,
                entity_category=entity_category,
                icon=icon,
                unique_suffix=unique_suffix,
            )
        )
    async_add_entities(entities)


class RgbStatusSensor(CoordinatorEntity, SensorEntity):
    """High-level online/offline status, based on consecutive fetch failures."""

    _attr_has_entity_name = True
    _attr_name = "Status"
    _attr_icon = "mdi:list-status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self):
        return "Online" if self.coordinator.device_online else "Offline"


class RgbFieldSensor(CoordinatorEntity, SensorEntity):
    """Generic sensor for a single field from coordinator data."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        *,
        name: str,
        path: list[str],
        unit: str | None,
        device_class: str | None,
        state_class: str | None,
        multiplier: float,
        entity_category: EntityCategory | None,
        icon: str | None,
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._path = path
        self._multiplier = multiplier
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_entity_category = entity_category
        self._attr_icon = icon
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def available(self) -> bool:
        if not self.coordinator.device_online:
            return False
        value = _read_path(self.coordinator.data, self._path)
        if self._attr_device_class == "power":
            return is_valid_power_usage(value)
        if self._attr_unique_id.endswith("_meter_url"):
            return bool(value)
        return value is not None

    @property
    def native_value(self):
        value = _read_path(self.coordinator.data, self._path)
        if self._attr_device_class == "power":
            return value if is_valid_power_usage(value) else None
        if isinstance(value, (int, float)) and self._multiplier not in (None, 1):
            return value / self._multiplier
        return value
