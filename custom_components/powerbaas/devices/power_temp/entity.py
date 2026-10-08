"""Shared device info and base classes for Powerbaas PowerTemp entities."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN
from .client import PowerTempCommandError
from .const import port_device_identifier, port_display_name


def hub_device_info(coordinator, entry: ConfigEntry) -> DeviceInfo:
    system = (coordinator.data or {}).get("system") or {}
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=coordinator.device_name,
        manufacturer="Powerbaas",
        model="Powerbaas PowerTemp",
        sw_version=str(system.get("firmwareVersion", "Unknown")),
        configuration_url=coordinator.device_url,
    )


def port_device_info(coordinator, entry: ConfigEntry, port: int) -> DeviceInfo:
    """Sub-device per connector port, linked to the hub via via_device."""
    port_data = ((coordinator.data or {}).get("ports") or {}).get(port) or {}
    return DeviceInfo(
        identifiers={port_device_identifier(entry.entry_id, port)},
        name=port_display_name(port, port_data.get("name")),
        manufacturer="Powerbaas",
        model="PowerTemp sensor",
        via_device=(DOMAIN, entry.entry_id),
    )


def read_path(data: Any, path: list[str]):
    for key in path:
        data = data.get(key) if isinstance(data, dict) else None
    return data


async def async_apply(coordinator, action) -> None:
    """Run a coordinator config command, surfacing firmware rejections in the UI."""
    try:
        await action
    except PowerTempCommandError as err:
        raise HomeAssistantError(
            f"{coordinator.device_name} rejected the change: {err.code}"
        ) from err


class PowerTempConfigEntity(CoordinatorEntity):
    """Hub-level entity backed by one /api/config value."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry: ConfigEntry, path: list[str], unique_suffix: str) -> None:
        super().__init__(coordinator)
        self._path = path
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        self._attr_device_info = hub_device_info(coordinator, entry)

    @property
    def _config_value(self):
        return read_path((self.coordinator.data or {}).get("config"), self._path)

    @property
    def available(self) -> bool:
        return self.coordinator.device_online and self._config_value is not None

    def _body(self, value) -> dict[str, Any]:
        """Nest ``value`` under this entity's config path, e.g. {"thresholds": {"warnC": 45}}."""
        body: Any = value
        for key in reversed(self._path):
            body = {key: body}
        return body
