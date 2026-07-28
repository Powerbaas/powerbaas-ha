import logging
from typing import Any, Callable, Dict, List, Optional

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util

from ...const import DOMAIN
from .const import MAIN_SENSORS, DIAGNOSTIC_SENSORS

_LOGGER = logging.getLogger(__name__)


def _integration_version(controller, config_entry: ConfigEntry) -> str:
    return str(controller.integration_version)


def _device_info(config_entry: ConfigEntry, controller) -> Dict[str, Any]:
    return {
        "identifiers": {(DOMAIN, config_entry.entry_id)},
        "name": config_entry.title,
        "manufacturer": "Powerbaas",
        "model": "Boiler Controller",
        "sw_version": controller.device_firmware_version,
        "configuration_url": controller.device_url,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    controller = hass.data[DOMAIN][config_entry.entry_id]["controller"]

    sensors: List[SensorEntity] = [
        BoilerControllerStatusSensor(hass, config_entry, controller),
        LastDimmerUpdateSensor(hass, config_entry, controller),
    ]

    for name, path, unit, device_class, state_class, multiplier, entity_category, icon, unique_suffix in (
        MAIN_SENSORS + DIAGNOSTIC_SENSORS
    ):
        sensors.append(
            BoilerControllerFieldSensor(
                hass, config_entry, controller,
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

class BoilerControllerStatusSensor(SensorEntity):
    """High-level status sensor for the controller."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass, config_entry, controller) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.controller = controller
        self._attr_name = f"{config_entry.title} Status"
        self._attr_unique_id = f"{config_entry.entry_id}_status"
        self._attr_icon = "mdi:list-status"
        self._remove_callbacks: List[Callable] = []

    async def async_added_to_hass(self) -> None:
        self._remove_callbacks.append(
            async_track_state_change_event(
                self.hass,
                list(self.controller._tracked_entities),
                self._handle_update,
            )
        )
        self._remove_callbacks.append(
            async_dispatcher_connect(
                self.hass,
                self.controller.get_device_status_signal(),
                self._handle_device_update,
            )
        )
        self._remove_callbacks.append(
            async_dispatcher_connect(
                self.hass,
                self.controller.get_calibration_state_signal(),
                self._handle_calibration_update,
            )
        )
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        for cb in self._remove_callbacks:
            cb()
        self._remove_callbacks.clear()

    @callback
    def _handle_update(self, event) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_device_update(self, status) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_calibration_update(self, active: bool) -> None:
        self.async_write_ha_state()

    @property
    def state(self) -> str:
        if not self.controller.is_device_online:
            return "Offline"
        if self.controller.is_calibration_active:
            return "Calibration"
        status = self.controller.get_device_status() or {}
        if status.get("errors"):
            return "Error"
        heating = status.get("heatingPercentage", 0)
        if heating and float(heating) > 0:
            return "Running"
        return "Idle"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {
            "power_sensor_type": self.controller.power_sensor_type,
            "power_sensor": self.controller.power_sensor_id,
            "return_sensor": self.controller.return_sensor_id,
            "usage_sensor": self.controller.usage_sensor_id,
            "device_url": self.controller.device_url,
            "poll_interval": f"{self.controller.poll_interval}s",
            "integration_version": _integration_version(self.controller, self.config_entry),
        }

        controller_status = self.controller.get_status()
        attrs.update(
            {
                "min_dimmer": controller_status.get("min_dimmer"),
                "max_dimmer": controller_status.get("max_dimmer"),
                "effective_min_dimmer": controller_status.get("effective_min_dimmer"),
                "effective_max_dimmer": controller_status.get("effective_max_dimmer"),
                "last_control_update": controller_status.get("last_control_update"),
                "manual_mode": controller_status.get("dimming_mode") == "manual",
                "calibration_active": controller_status.get("calibration_active", False),
                "calibration_points": controller_status.get("calibration_points", 0),
                "calibration_created": controller_status.get("calibration_created"),
            }
        )

        # Per-sensor status (handles both net and split configurations)
        missing_any = False
        for label, entity_id in (
            ("power_sensor", self.controller.power_sensor_id),
            ("return_sensor", self.controller.return_sensor_id),
            ("usage_sensor", self.controller.usage_sensor_id),
        ):
            if not entity_id:
                continue
            state = self.hass.states.get(entity_id)
            if state:
                attrs[f"{label}_status"] = "available"
                attrs[f"{label}_value"] = state.state
                attrs[f"{label}_unit"] = state.attributes.get(
                    "unit_of_measurement", "W"
                )
            else:
                attrs[f"{label}_status"] = "missing"
                missing_any = True
        attrs["sensors_status"] = "missing" if missing_any else "available"

        if self.controller._last_control_update:
            attrs["last_control_update"] = self.controller._last_control_update.isoformat()
        if self.controller._last_power_value is not None:
            attrs["last_power_value"] = self.controller._last_power_value

        return attrs

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.config_entry, self.controller)


class LastDimmerUpdateSensor(SensorEntity):
    """Sensor showing when the controller last adjusted the heating percentage."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass, config_entry, controller) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.controller = controller
        self._attr_name = f"{config_entry.title} Last Control Update"
        self._attr_unique_id = f"{config_entry.entry_id}_last_dimmer_update"
        self._attr_icon = "mdi:clock-outline"
        self._remove_callbacks: List[Callable] = []

    async def async_added_to_hass(self) -> None:
        self._remove_callbacks.append(
            async_track_state_change_event(
                self.hass,
                list(self.controller._tracked_entities),
                self._handle_update,
            )
        )
        self._remove_callbacks.append(
            async_dispatcher_connect(
                self.hass,
                self.controller.get_device_status_signal(),
                self._handle_dispatcher_update,
            )
        )
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        for cb in self._remove_callbacks:
            cb()
        self._remove_callbacks.clear()

    @callback
    def _handle_update(self, event) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_dispatcher_update(self, status) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self):
        value = self.controller._last_control_update
        if isinstance(value, str):
            parsed = dt_util.parse_datetime(value)
            if parsed is not None:
                return parsed
        return value

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        attrs = {
            "update_method": "event_driven",
            "integration_version": _integration_version(self.controller, self.config_entry),
        }
        if self.controller._last_power_value is not None:
            attrs["last_power_value"] = self.controller._last_power_value
        return attrs

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.config_entry, self.controller)


# ---------------------------------------------------------------------------
# Flat field-mapped sensors (fed by controller polling loop) - built from
# MAIN_SENSORS/DIAGNOSTIC_SENSORS in const.py, mirroring the p1_meter pattern.
# ---------------------------------------------------------------------------

class BoilerControllerFieldSensor(SensorEntity):
    """Generic sensor for a single flat field from /api/status or /api/system.

    Unavailable (not "unknown") whenever the root section hasn't been polled
    yet, or the field itself is present but null - e.g. temperatureExternal
    when no probe is mapped to that role.
    """

    _attr_should_poll = False

    def __init__(
        self,
        hass,
        config_entry,
        controller,
        *,
        name: str,
        path: List[str],
        unit: Optional[str],
        device_class: Optional[str],
        state_class: Optional[str],
        multiplier: float,
        entity_category: Optional[EntityCategory],
        icon: Optional[str],
        unique_suffix: str,
    ) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.controller = controller
        self._path = path
        self._multiplier = multiplier
        self._attr_name = f"{config_entry.title} {name}"
        self._attr_unique_id = f"{config_entry.entry_id}_{unique_suffix}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_entity_category = entity_category
        self._attr_icon = icon
        self._attr_available = False
        self._attr_native_value = None
        self._remove_dispatcher: Optional[Callable] = None

    async def async_added_to_hass(self) -> None:
        self._remove_dispatcher = async_dispatcher_connect(
            self.hass,
            self.controller.get_device_status_signal(),
            self._handle_update,
        )
        self._refresh()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_dispatcher:
            self._remove_dispatcher()
            self._remove_dispatcher = None

    @callback
    def _handle_update(self, status) -> None:
        self._refresh()
        self.async_write_ha_state()

    def _refresh(self) -> None:
        value = self._extract_value()
        self._attr_available = value is not None
        self._attr_native_value = value

    def _get_root(self) -> Optional[Dict[str, Any]]:
        section = self._path[0]
        if section == "status":
            return self.controller.get_device_status()
        if section == "system":
            system_info = self.controller.get_system_status()
            return system_info.get("system") if system_info is not None else None
        return None

    def _extract_value(self):
        data = self._get_root()
        for key in self._path[1:]:
            if not isinstance(data, dict):
                return None
            data = data.get(key)
        if isinstance(data, (int, float)) and self._multiplier not in (None, 1):
            return data / self._multiplier
        return data

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.config_entry, self.controller)
