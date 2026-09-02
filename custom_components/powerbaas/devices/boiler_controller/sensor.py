import logging
from typing import Any, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN
from .const import BOILER_MODE_MANUAL, MAIN_SENSORS, DIAGNOSTIC_SENSORS

_LOGGER = logging.getLogger(__name__)


def _device_info(coordinator, config_entry: ConfigEntry) -> dict[str, Any]:
    system = (coordinator.data or {}).get("system") or {}
    return {
        "identifiers": {(DOMAIN, config_entry.entry_id)},
        "name": config_entry.title,
        "manufacturer": "Powerbaas",
        "model": "Boiler Controller",
        "sw_version": str(system.get("firmwareVersion", "Unknown")),
        "configuration_url": coordinator.device_url,
    }


def _read_path(data: Any, path: list[str]):
    for key in path:
        data = data.get(key) if isinstance(data, dict) else None
    return data


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    sensors: list[SensorEntity] = [
        BoilerControllerStatusSensor(coordinator, config_entry),
    ]

    for name, path, unit, device_class, state_class, multiplier, entity_category, icon, unique_suffix in (
        MAIN_SENSORS + DIAGNOSTIC_SENSORS
    ):
        sensors.append(
            BoilerControllerFieldSensor(
                coordinator, config_entry,
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

    async_add_entities(sensors)


# ---------------------------------------------------------------------------
# Status / diagnostics
# ---------------------------------------------------------------------------

class BoilerControllerStatusSensor(CoordinatorEntity, SensorEntity):
    """High-level status sensor for the controller."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self._attr_name = f"{config_entry.title} Status"
        self._attr_unique_id = f"{config_entry.entry_id}_status"
        self._attr_icon = "mdi:list-status"

    @property
    def available(self) -> bool:
        return True

    @property
    def state(self) -> str:
        if not self.coordinator.device_online:
            return "Offline"
        data = self.coordinator.data or {}
        if data.get("calibration_active"):
            return "Calibration"
        status = data.get("status") or {}
        if status.get("errors"):
            return "Error"
        heating = status.get("heatingPercentage", 0)
        if heating and float(heating) > 0:
            return "Running"
        return "Idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        coordinator = self.coordinator
        data = coordinator.data or {}
        attrs: dict[str, Any] = {
            "power_sensor_type": coordinator.power_sensor_type,
            "power_sensor": coordinator.power_sensor_id,
            "return_sensor": coordinator.return_sensor_id,
            "usage_sensor": coordinator.usage_sensor_id,
            "device_url": coordinator.device_url,
            "poll_interval": f"{coordinator.poll_interval}s",
            "integration_version": str(coordinator.integration_version),
            "min_dimmer": None,
            "max_dimmer": None,
            "effective_min_dimmer": None,
            "effective_max_dimmer": None,
            "manual_mode": data.get("control_mode") == BOILER_MODE_MANUAL,
            "calibration_active": data.get("calibration_active", False),
            "calibration_points": 0,
            "calibration_created": None,
        }

        # Per-sensor status (handles both net and split configurations)
        missing_any = False
        for label, entity_id in (
            ("power_sensor", coordinator.power_sensor_id),
            ("return_sensor", coordinator.return_sensor_id),
            ("usage_sensor", coordinator.usage_sensor_id),
        ):
            if not entity_id:
                continue
            state = self.hass.states.get(entity_id)
            if state:
                attrs[f"{label}_status"] = "available"
                attrs[f"{label}_value"] = state.state
                attrs[f"{label}_unit"] = state.attributes.get("unit_of_measurement", "W")
            else:
                attrs[f"{label}_status"] = "missing"
                missing_any = True
        attrs["sensors_status"] = "missing" if missing_any else "available"

        if coordinator._last_power_value is not None:
            attrs["last_power_value"] = coordinator._last_power_value

        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _device_info(self.coordinator, self.config_entry)


# ---------------------------------------------------------------------------
# Flat field-mapped sensors (fed by the coordinator's poll data) - built from
# MAIN_SENSORS/DIAGNOSTIC_SENSORS in const.py, mirroring the p1_meter/rgb/
# airco_bridge pattern.
# ---------------------------------------------------------------------------

class BoilerControllerFieldSensor(CoordinatorEntity, SensorEntity):
    """Generic sensor for a single flat field from /api/status or /api/system.

    Unavailable whenever the device is offline, or the field itself is
    present but null - e.g. temperatureExternal when no probe is mapped to
    that role.
    """

    _attr_should_poll = False

    def __init__(
        self,
        coordinator,
        config_entry: ConfigEntry,
        *,
        name: str,
        path: list[str],
        unit: Optional[str],
        device_class: Optional[str],
        state_class: Optional[str],
        multiplier: float,
        entity_category: Optional[EntityCategory],
        icon: Optional[str],
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self._path = path
        self._multiplier = multiplier
        self._attr_name = f"{config_entry.title} {name}"
        self._attr_unique_id = f"{config_entry.entry_id}_{unique_suffix}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_entity_category = entity_category
        self._attr_icon = icon

    def _extract_value(self):
        return _read_path(self.coordinator.data, self._path)

    @property
    def available(self) -> bool:
        return self.coordinator.device_online and self._extract_value() is not None

    @property
    def native_value(self):
        value = self._extract_value()
        if isinstance(value, (int, float)) and self._multiplier not in (None, 1):
            return value / self._multiplier
        return value

    @property
    def device_info(self) -> dict[str, Any]:
        return _device_info(self.coordinator, self.config_entry)
