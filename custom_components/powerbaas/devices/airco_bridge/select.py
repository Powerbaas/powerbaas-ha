"""Select entity for the Airco Bridge IR protocol."""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN
from .const import DEFAULT_TEMPERATURE, clamp_temperature


def _device_info(coordinator, entry: ConfigEntry) -> DeviceInfo:
    system = (coordinator.data or {}).get("system") or {}
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=coordinator.device_name,
        manufacturer="Powerbaas",
        model="Airco Bridge",
        sw_version=str(system.get("firmwareVersion", "Unknown")),
        configuration_url=coordinator.device_url,
    )


def _protocol_options(ir_types: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """Return (label, value) pairs sorted alphabetically by label."""
    options: list[tuple[str, int]] = []
    seen_labels: set[str] = set()
    for item in ir_types:
        try:
            value = int(item.get("value"))
        except (TypeError, ValueError):
            continue
        label = str(item.get("key") or value)
        if label in seen_labels:
            label = f"{label} ({value})"
        seen_labels.add(label)
        options.append((label, value))
    options.sort(key=lambda pair: pair[0].lower())
    return options


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([AircoBridgeProtocolSelect(coordinator, entry)])


class AircoBridgeProtocolSelect(CoordinatorEntity, SelectEntity):
    """Pick the IR protocol the bridge uses when sending commands."""

    _attr_has_entity_name = True
    _attr_name = "Protocol"
    _attr_icon = "mdi:infrared"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_protocol"
        self._attr_device_info = _device_info(coordinator, entry)

    def _option_maps(self) -> tuple[dict[str, int], dict[int, str]]:
        pairs = _protocol_options(self.coordinator.ir_types)
        label_to_value = {label: value for label, value in pairs}
        value_to_label = {value: label for label, value in pairs}
        return label_to_value, value_to_label

    @property
    def options(self) -> list[str]:
        label_to_value, _ = self._option_maps()
        return list(label_to_value)

    @property
    def available(self) -> bool:
        return self.coordinator.device_online and bool(self.options)

    @property
    def current_option(self) -> str | None:
        airco = (self.coordinator.data or {}).get("airco") or {}
        type_id = airco.get("type")
        if type_id is None:
            return None
        try:
            type_id = int(type_id)
        except (TypeError, ValueError):
            return None
        _, value_to_label = self._option_maps()
        return value_to_label.get(type_id)

    async def async_select_option(self, option: str) -> None:
        label_to_value, _ = self._option_maps()
        if option not in label_to_value:
            raise HomeAssistantError(f"Unknown IR protocol: {option}")
        airco = (self.coordinator.data or {}).get("airco") or {}
        mode = airco.get("mode", -1)
        if not airco.get("ison"):
            mode = -1
        ok = await self.coordinator.client.async_control(
            type_id=label_to_value[option],
            mode=int(mode),
            fanspeed=int(airco.get("fanspeed", 0)),
            temperature=clamp_temperature(airco.get("degrees") or DEFAULT_TEMPERATURE),
        )
        if not ok:
            raise HomeAssistantError("Failed to set IR protocol on the Airco Bridge")
        await self.coordinator.async_request_refresh()
