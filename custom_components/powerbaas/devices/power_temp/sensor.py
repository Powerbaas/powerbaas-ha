"""Sensor entities for the Powerbaas PowerTemp."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN
from .const import DIAGNOSTIC_SENSORS, MAIN_SENSORS, OVERALL_STATES, PORT_STATES


def _device_info(coordinator, entry: ConfigEntry) -> DeviceInfo:
    system = (coordinator.data or {}).get("system") or {}
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=coordinator.device_name,
        manufacturer="Powerbaas",
        model="Powerbaas PowerTemp",
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
    entities: list[SensorEntity] = [
        PowerTempStatusSensor(coordinator, entry),
        PowerTempOverallStatusSensor(coordinator, entry),
    ]
    for name, path, unit, device_class, state_class, multiplier, entity_category, icon, unique_suffix in (
        MAIN_SENSORS + DIAGNOSTIC_SENSORS
    ):
        entities.append(
            PowerTempFieldSensor(
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

    # Sensors can be plugged into a port at any time (picked up by the
    # firmware's periodic scan), so add entities for ports as they appear.
    known_ports: set[int] = set()

    @callback
    def _add_new_ports() -> None:
        ports = (coordinator.data or {}).get("ports") or {}
        new_ports = sorted(set(ports) - known_ports)
        if not new_ports:
            return
        known_ports.update(new_ports)
        new_entities: list[SensorEntity] = []
        for port in new_ports:
            new_entities.append(PowerTempPortTemperatureSensor(coordinator, entry, port))
            new_entities.append(PowerTempPortStatusSensor(coordinator, entry, port))
        async_add_entities(new_entities)

    _add_new_ports()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_ports))


class PowerTempStatusSensor(CoordinatorEntity, SensorEntity):
    """High-level online/offline status, based on consecutive fetch failures."""

    _attr_should_poll = False
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


class PowerTempOverallStatusSensor(CoordinatorEntity, SensorEntity):
    """Worst level across all enabled ports, as reported by the firmware."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Overall Status"
    _attr_icon = "mdi:thermometer-alert"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = OVERALL_STATES

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_overall_status"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def available(self) -> bool:
        return self.coordinator.device_online and self.native_value is not None

    @property
    def native_value(self):
        value = _read_path(self.coordinator.data, ["sensors", "status"])
        return value if value in OVERALL_STATES else None


class PowerTempFieldSensor(CoordinatorEntity, SensorEntity):
    """Generic sensor for a single field from coordinator data."""

    _attr_should_poll = False
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
        return _read_path(self.coordinator.data, self._path) is not None

    @property
    def native_value(self):
        value = _read_path(self.coordinator.data, self._path)
        if isinstance(value, (int, float)) and self._multiplier not in (None, 1):
            return value / self._multiplier
        return value


class _PowerTempPortEntity(CoordinatorEntity, SensorEntity):
    """Base for entities tied to one connector port (1-16).

    unique_id is keyed by port number, not by the user-given name, so
    renaming a sensor on the device keeps the same entity.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _name_suffix = ""

    def __init__(self, coordinator, entry: ConfigEntry, port: int) -> None:
        super().__init__(coordinator)
        self._port = port
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def _port_data(self) -> dict | None:
        return ((self.coordinator.data or {}).get("ports") or {}).get(self._port)

    @property
    def name(self) -> str:
        port_name = (self._port_data or {}).get("name") or f"Port {self._port}"
        return f"{port_name}{self._name_suffix}"

    @property
    def available(self) -> bool:
        return self.coordinator.device_online and self._port_data is not None


class PowerTempPortTemperatureSensor(_PowerTempPortEntity):
    """Temperature measured on one port (offset already applied by firmware)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator, entry: ConfigEntry, port: int) -> None:
        super().__init__(coordinator, entry, port)
        self._attr_unique_id = f"{entry.entry_id}_port_{port}_temperature"

    @property
    def available(self) -> bool:
        return super().available and self._port_data.get("celsius") is not None

    @property
    def native_value(self):
        return (self._port_data or {}).get("celsius")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._port_data or {}
        return {
            "port": self._port,
            "sensor_type": data.get("type"),
            "status": data.get("status"),
            "delta_c": data.get("deltaC"),
            "age_s": data.get("ageS"),
            "ambient": data.get("ambient"),
            "enabled": data.get("enabled"),
        }


class PowerTempPortStatusSensor(_PowerTempPortEntity):
    """Per-port level (ok/warning/alarm) or sensor fault (missing/error/disabled)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = PORT_STATES
    _attr_icon = "mdi:thermometer-check"
    _name_suffix = " Status"

    def __init__(self, coordinator, entry: ConfigEntry, port: int) -> None:
        super().__init__(coordinator, entry, port)
        self._attr_unique_id = f"{entry.entry_id}_port_{port}_status"

    @property
    def native_value(self):
        value = (self._port_data or {}).get("status")
        return value if value in PORT_STATES else None
