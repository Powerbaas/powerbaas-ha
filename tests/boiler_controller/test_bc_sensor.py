"""Field/status sensor behavior against a fake coordinator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.powerbaas.devices.boiler_controller.const import MAIN_SENSORS
from custom_components.powerbaas.devices.boiler_controller.sensor import (
    BoilerControllerFieldSensor,
    BoilerControllerStatusSensor,
)


def _field_sensor(
    unique_suffix: str, *, status: dict | None, online: bool = True
) -> BoilerControllerFieldSensor:
    coordinator = SimpleNamespace(data={"status": status, "system": {}}, device_online=online)
    entry = MagicMock()
    entry.entry_id = "bc_entry"
    field = next(f for f in MAIN_SENSORS if f[-1] == unique_suffix)
    name, path, unit, device_class, state_class, multiplier, entity_category, icon, suffix = field
    sensor = object.__new__(BoilerControllerFieldSensor)
    sensor.coordinator = coordinator
    sensor.config_entry = entry
    sensor._path = path
    sensor._multiplier = multiplier
    sensor._attr_name = name
    sensor._attr_unique_id = f"{entry.entry_id}_{suffix}"
    sensor._attr_native_unit_of_measurement = unit
    sensor._attr_device_class = device_class
    sensor._attr_state_class = state_class
    sensor._attr_entity_category = entity_category
    sensor._attr_icon = icon
    return sensor


def test_field_sensor_available_when_field_present() -> None:
    sensor = _field_sensor("device_power", status={"power": 400})

    assert BoilerControllerFieldSensor.available.fget(sensor) is True
    assert BoilerControllerFieldSensor.native_value.fget(sensor) == 400


def test_field_sensor_unavailable_when_field_null() -> None:
    """e.g. temperatureExternal when no probe is mapped to that role."""
    sensor = _field_sensor("device_temperature_external", status={"temperatureExternal": None})

    assert BoilerControllerFieldSensor.available.fget(sensor) is False


def test_field_sensor_unavailable_when_offline() -> None:
    sensor = _field_sensor("device_power", status={"power": 400}, online=False)

    assert BoilerControllerFieldSensor.available.fget(sensor) is False


def _status_sensor(
    *, online: bool, calibration_active: bool = False, status: dict | None = None
) -> BoilerControllerStatusSensor:
    coordinator = SimpleNamespace(
        data={"status": status or {}, "calibration_active": calibration_active},
        device_online=online,
        power_sensor_type="net",
        power_sensor_id="sensor.net_power",
        return_sensor_id=None,
        usage_sensor_id=None,
        device_url="http://bc.local",
        poll_interval=10,
        integration_version="1.0",
        _last_power_value=None,
    )
    entry = MagicMock()
    entry.entry_id = "bc_entry"
    entry.title = "Test BC"
    sensor = object.__new__(BoilerControllerStatusSensor)
    sensor.coordinator = coordinator
    sensor.config_entry = entry
    sensor.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: None))
    return sensor


def test_status_sensor_always_available() -> None:
    sensor = _status_sensor(online=False)

    assert BoilerControllerStatusSensor.available.fget(sensor) is True


def test_status_sensor_offline_state() -> None:
    sensor = _status_sensor(online=False)

    assert BoilerControllerStatusSensor.state.fget(sensor) == "Offline"


def test_status_sensor_calibration_state() -> None:
    sensor = _status_sensor(online=True, calibration_active=True)

    assert BoilerControllerStatusSensor.state.fget(sensor) == "Calibration"


def test_status_sensor_running_state() -> None:
    sensor = _status_sensor(online=True, status={"heatingPercentage": 50})

    assert BoilerControllerStatusSensor.state.fget(sensor) == "Running"


def test_status_sensor_idle_state() -> None:
    sensor = _status_sensor(online=True, status={"heatingPercentage": 0})

    assert BoilerControllerStatusSensor.state.fget(sensor) == "Idle"
