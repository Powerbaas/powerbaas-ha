"""Field-sensor path mapping against a fake coordinator, incl. Meter URL."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.powerbaas.devices.rgb.const import DIAGNOSTIC_SENSORS
from custom_components.powerbaas.devices.rgb.sensor import RgbFieldSensor


def _meter_url_sensor(*, system: dict, online: bool = True) -> RgbFieldSensor:
    coordinator = SimpleNamespace(
        data={"rgb": {}, "system": system},
        device_online=online,
        device_name="Powerbaas RGB",
        device_url="http://rgb.local",
    )
    entry = MagicMock()
    entry.entry_id = "rgb_entry"
    field = next(f for f in DIAGNOSTIC_SENSORS if f[-1] == "meter_url")
    name, path, unit, device_class, state_class, multiplier, entity_category, icon, unique_suffix = field
    sensor = object.__new__(RgbFieldSensor)
    sensor.coordinator = coordinator
    sensor._path = path
    sensor._multiplier = multiplier
    sensor._attr_name = name
    sensor._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
    sensor._attr_native_unit_of_measurement = unit
    sensor._attr_device_class = device_class
    sensor._attr_state_class = state_class
    sensor._attr_entity_category = entity_category
    sensor._attr_icon = icon
    sensor._attr_device_info = {}
    return sensor


# Regression test: the sensor read from the wrong firmware field name
# ("system.meterUrl" instead of the actual "system.p1MeterUrl"), so it
# always read None and showed "Unavailable" even in Powerbaas/HomeWizard
# mode with a real meter linked. Confirmed against a real ring's
# /api/system response.


def test_meter_url_available_when_linked() -> None:
    sensor = _meter_url_sensor(
        system={"mode": "Powerbaas", "p1MeterUrl": "http://192.168.30.207/"}
    )

    assert RgbFieldSensor.available.fget(sensor) is True
    assert RgbFieldSensor.native_value.fget(sensor) == "http://192.168.30.207/"


def test_meter_url_unavailable_in_standalone() -> None:
    sensor = _meter_url_sensor(system={"mode": "Standalone", "p1MeterUrl": ""})

    assert RgbFieldSensor.available.fget(sensor) is False
