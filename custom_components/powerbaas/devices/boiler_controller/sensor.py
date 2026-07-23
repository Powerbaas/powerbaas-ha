import logging
from typing import Any, Callable, Dict, List, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util

try:
    from homeassistant.const import (
        PERCENTAGE,
        UnitOfEnergy,
        UnitOfPower,
        UnitOfTemperature,
    )

    UNIT_POWER = UnitOfPower.WATT
    UNIT_TEMP = UnitOfTemperature.CELSIUS
    UNIT_ENERGY = UnitOfEnergy.KILO_WATT_HOUR
except ImportError:
    from homeassistant.const import PERCENTAGE

    UNIT_POWER = "W"
    UNIT_TEMP = "°C"
    UNIT_ENERGY = "kWh"

from ...const import DOMAIN

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
    }


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    controller = hass.data[DOMAIN][config_entry.entry_id]["controller"]

    sensors: List[SensorEntity] = [
        BoilerControllerStatusSensor(hass, config_entry, controller),
        *_build_power_source_sensors(hass, config_entry, controller),
        LastDimmerUpdateSensor(hass, config_entry, controller),
        # Device sensors from /api/status
        DevicePowerSensor(hass, config_entry, controller),
        DeviceHeatingPercentageSensor(hass, config_entry, controller),
        DeviceTemperatureSensor(hass, config_entry, controller),
        DeviceEnergySensor(hass, config_entry, controller),
        DeviceRssiSensor(hass, config_entry, controller),
        DevicePowerSourceSensor(hass, config_entry, controller),
        # System sensors from /api/system
        DeviceFirmwareVersionSensor(hass, config_entry, controller),
        DeviceWifiStrengthSensor(hass, config_entry, controller),
        DeviceUptimeSensor(hass, config_entry, controller),
        DeviceUpSinceSensor(hass, config_entry, controller),
        DeviceIpSensor(hass, config_entry, controller),
    ]

    async_add_entities(sensors)


# ---------------------------------------------------------------------------
# Status / diagnostics
# ---------------------------------------------------------------------------

class BoilerControllerStatusSensor(SensorEntity):
    """High-level status sensor for the controller."""

    _attr_should_poll = False

    def __init__(self, hass, config_entry, controller) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.controller = controller
        self._attr_name = f"{config_entry.title} Status"
        self._attr_unique_id = f"{config_entry.entry_id}_status"
        self._attr_icon = "mdi:thermostat"
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
                self.controller.get_shelly_status_signal(),
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


class PowerSourceMirrorSensor(SensorEntity):
    """Mirror a single configured power source entity as a diagnostic sensor.

    One instance is registered per configured source: a single sensor in
    net mode, or two sensors (return + usage) in split mode.
    """

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hass,
        config_entry,
        controller,
        source_entity_id: str,
        name_suffix: str,
        unique_id_suffix: str,
    ) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.controller = controller
        self._source_entity_id = source_entity_id
        self._attr_name = f"{config_entry.title} {name_suffix}"
        self._attr_unique_id = f"{config_entry.entry_id}_{unique_id_suffix}"
        self._remove_callbacks: List[Callable] = []

    async def async_added_to_hass(self) -> None:
        self._remove_callbacks.append(
            async_track_state_change_event(
                self.hass,
                [self._source_entity_id],
                self._handle_update,
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

    @property
    def native_value(self) -> Optional[float]:
        state = self.hass.states.get(self._source_entity_id)
        if not state:
            return None
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return None
        return self._normalize_power_unit(value, self._extract_unit(state))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        state = self.hass.states.get(self._source_entity_id)
        if not state:
            return {"source_entity": self._source_entity_id, "status": "missing"}
        return {
            "source_entity": self._source_entity_id,
            "status": "available",
            "last_changed": state.last_changed.isoformat(),
            "last_updated": state.last_updated.isoformat(),
            "unit": self._extract_unit(state) or "",
        }

    @staticmethod
    def _extract_unit(state) -> str:
        unit = state.attributes.get("unit_of_measurement") or state.attributes.get(
            "native_unit_of_measurement"
        )
        return str(unit).strip() if unit else ""

    @staticmethod
    def _normalize_power_unit(power_value: float, unit: str) -> float:
        if not unit:
            return power_value
        cleaned = unit.strip().lower()
        if cleaned.startswith("kw") or "kilowatt" in cleaned:
            return power_value * 1000
        return power_value

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.config_entry, self.controller)


def _build_power_source_sensors(
    hass, config_entry, controller
) -> List["PowerSourceMirrorSensor"]:
    """Return one or two mirror sensors depending on the configured mode."""
    from .const import POWER_SENSOR_TYPE_SPLIT

    if controller.power_sensor_type == POWER_SENSOR_TYPE_SPLIT:
        return [
            PowerSourceMirrorSensor(
                hass,
                config_entry,
                controller,
                controller.return_sensor_id,
                name_suffix="Grid Return",
                unique_id_suffix="return_sensor",
            ),
            PowerSourceMirrorSensor(
                hass,
                config_entry,
                controller,
                controller.usage_sensor_id,
                name_suffix="Grid Usage",
                unique_id_suffix="usage_sensor",
            ),
        ]

    return [
        PowerSourceMirrorSensor(
            hass,
            config_entry,
            controller,
            controller.power_sensor_id,
            name_suffix="Net Power",
            unique_id_suffix="power_sensor",
        )
    ]


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
                self.controller.get_shelly_status_signal(),
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
# BC device sensors (fed by controller polling loop)
# ---------------------------------------------------------------------------

class DeviceSensorBase(SensorEntity):
    """Base for sensors that subscribe to the device polling dispatcher."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hass,
        config_entry,
        controller,
        *,
        name_suffix: str,
        unique_suffix: str,
        icon: Optional[str] = None,
    ) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.controller = controller
        self._attr_name = f"{config_entry.title} {name_suffix}"
        self._attr_unique_id = f"{config_entry.entry_id}_{unique_suffix}"
        self._attr_icon = icon
        self._attr_available = False
        self._attr_native_value = None
        self._remove_dispatcher: Optional[Callable] = None

    async def async_added_to_hass(self) -> None:
        self._remove_dispatcher = async_dispatcher_connect(
            self.hass,
            self.controller.get_shelly_status_signal(),
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
        status = self._get_status()
        if status is None:
            self._attr_available = False
            self._attr_native_value = None
        else:
            self._attr_available = True
            self._attr_native_value = self._extract_value(status)

    def _get_status(self) -> Optional[Dict[str, Any]]:
        return self.controller.get_device_status()

    def _extract_value(self, status: Dict[str, Any]):
        raise NotImplementedError

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.config_entry, self.controller)


class SystemSensorBase(DeviceSensorBase):
    """Base for sensors that read from /api/system data."""

    def _get_status(self) -> Optional[Dict[str, Any]]:
        system_info = self.controller.get_system_status()
        if system_info is None:
            return None
        return system_info.get("system")


# --- /api/status sensors ---

class DevicePowerSensor(DeviceSensorBase):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UNIT_POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = None  # Show on dashboard by default

    def __init__(self, hass, config_entry, controller) -> None:
        super().__init__(
            hass, config_entry, controller,
            name_suffix="Device Power",
            unique_suffix="device_power",
            icon="mdi:flash",
        )

    def _extract_value(self, status):
        val = status.get("power")
        if isinstance(val, (int, float)):
            return round(float(val), 1)
        return None


class DeviceHeatingPercentageSensor(DeviceSensorBase):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = None

    def __init__(self, hass, config_entry, controller) -> None:
        super().__init__(
            hass, config_entry, controller,
            name_suffix="Heating Percentage",
            unique_suffix="device_heating_percentage",
            icon="mdi:brightness-percent",
        )

    def _extract_value(self, status):
        val = status.get("heatingPercentage")
        if isinstance(val, (int, float)):
            return int(val)
        return None


class DeviceTemperatureSensor(DeviceSensorBase):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UNIT_TEMP
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = None

    def __init__(self, hass, config_entry, controller) -> None:
        super().__init__(
            hass, config_entry, controller,
            name_suffix="Device Temperature",
            unique_suffix="device_temperature",
            icon="mdi:thermometer",
        )

    def _extract_value(self, status):
        val = status.get("temperature")
        if isinstance(val, (int, float)):
            return round(float(val), 1)
        return None


class DeviceEnergySensor(DeviceSensorBase):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UNIT_ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hass, config_entry, controller) -> None:
        super().__init__(
            hass, config_entry, controller,
            name_suffix="Device Energy",
            unique_suffix="device_energy",
            icon="mdi:lightning-bolt",
        )

    def _extract_value(self, status):
        val = status.get("total")
        if isinstance(val, (int, float)):
            return round(float(val), 3)
        return None


class DeviceRssiSensor(DeviceSensorBase):
    _attr_native_unit_of_measurement = "dBm"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass, config_entry, controller) -> None:
        super().__init__(
            hass, config_entry, controller,
            name_suffix="Device RSSI",
            unique_suffix="device_rssi",
            icon="mdi:wifi",
        )

    def _extract_value(self, status):
        val = status.get("rssi")
        if isinstance(val, (int, float)):
            return int(val)
        return None


class DevicePowerSourceSensor(DeviceSensorBase):
    def __init__(self, hass, config_entry, controller) -> None:
        super().__init__(
            hass, config_entry, controller,
            name_suffix="Power Source",
            unique_suffix="device_power_source",
            icon="mdi:power-plug",
        )

    def _extract_value(self, status):
        return status.get("measuredPowerSource")


# --- /api/system sensors ---

class DeviceFirmwareVersionSensor(SystemSensorBase):
    def __init__(self, hass, config_entry, controller) -> None:
        super().__init__(
            hass, config_entry, controller,
            name_suffix="Firmware Version",
            unique_suffix="device_firmware_version",
            icon="mdi:chip",
        )

    def _extract_value(self, status):
        return status.get("firmwareVersion")


class DeviceWifiStrengthSensor(SystemSensorBase):
    _attr_native_unit_of_measurement = "dBm"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass, config_entry, controller) -> None:
        super().__init__(
            hass, config_entry, controller,
            name_suffix="WiFi Strength",
            unique_suffix="device_wifi_strength",
            icon="mdi:wifi-strength-2",
        )

    def _extract_value(self, status):
        val = status.get("wifiStrength")
        if isinstance(val, (int, float)):
            return int(val)
        return None


class DeviceUptimeSensor(SystemSensorBase):
    _attr_native_unit_of_measurement = "s"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hass, config_entry, controller) -> None:
        super().__init__(
            hass, config_entry, controller,
            name_suffix="Uptime",
            unique_suffix="device_uptime",
            icon="mdi:timer-outline",
        )

    def _extract_value(self, status):
        val = status.get("uptimeSeconds")
        if isinstance(val, (int, float)):
            return int(val)
        return None


class DeviceUpSinceSensor(SystemSensorBase):
    def __init__(self, hass, config_entry, controller) -> None:
        super().__init__(
            hass, config_entry, controller,
            name_suffix="Up Since",
            unique_suffix="device_up_since",
            icon="mdi:calendar-clock",
        )

    def _extract_value(self, status):
        return status.get("upSince")


class DeviceIpSensor(SystemSensorBase):
    def __init__(self, hass, config_entry, controller) -> None:
        super().__init__(
            hass, config_entry, controller,
            name_suffix="IP Address",
            unique_suffix="device_ip",
            icon="mdi:ip-network",
        )

    def _extract_value(self, status):
        return status.get("ip")
