"""Status must not flip to Running while the boiler draws no power.

Auto mode can command a tiny target (e.g. ~25W -> 1%) on a small export;
with the boiler's thermostat satisfied it draws 0W, yet Status flapped
between Idle and Running every minute because it only looked at
heatingPercentage.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.powerbaas.devices.boiler_controller.sensor import (
    BoilerControllerStatusSensor,
)


def _status_sensor(status: dict) -> BoilerControllerStatusSensor:
    coordinator = SimpleNamespace(
        data={"status": status, "calibration_active": False},
        device_online=True,
    )
    entry = MagicMock()
    entry.entry_id = "bc_entry"
    entry.title = "Test BC"
    sensor = object.__new__(BoilerControllerStatusSensor)
    sensor.coordinator = coordinator
    sensor.config_entry = entry
    return sensor


def test_idle_when_commanded_but_drawing_no_power() -> None:
    sensor = _status_sensor({"heatingPercentage": 1, "power": 0})

    assert BoilerControllerStatusSensor.state.fget(sensor) == "Idle"


def test_running_when_drawing_power() -> None:
    sensor = _status_sensor({"heatingPercentage": 1, "power": 24})

    assert BoilerControllerStatusSensor.state.fget(sensor) == "Running"
