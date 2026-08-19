"""Firmware <-> Home Assistant mapping helpers for the Airco Bridge."""

from homeassistant.components.climate import HVACMode

from custom_components.powerbaas.devices.airco_bridge.const import (
    TEMP_DISCONNECTED_C,
    clamp_temperature,
    fan_mode_from_status,
    hvac_mode_from_status,
    is_valid_temperature,
)


def test_hvac_mode_from_status_off_when_not_on() -> None:
    assert hvac_mode_from_status({"ison": False, "mode": 1}) == HVACMode.OFF
    assert hvac_mode_from_status({}) == HVACMode.OFF
    assert hvac_mode_from_status(None) == HVACMode.OFF


def test_hvac_mode_from_status_maps_firmware_modes() -> None:
    assert hvac_mode_from_status({"ison": True, "mode": 0}) == HVACMode.AUTO
    assert hvac_mode_from_status({"ison": True, "mode": 1}) == HVACMode.COOL
    assert hvac_mode_from_status({"ison": True, "mode": 2}) == HVACMode.HEAT
    assert hvac_mode_from_status({"ison": True, "mode": 3}) == HVACMode.DRY
    assert hvac_mode_from_status({"ison": True, "mode": 4}) == HVACMode.FAN_ONLY


def test_fan_mode_from_status_maps_firmware_speeds() -> None:
    assert fan_mode_from_status({"fanspeed": 0}) == "auto"
    assert fan_mode_from_status({"fanspeed": 1}) == "min"
    assert fan_mode_from_status({"fanspeed": 3}) == "medium"
    assert fan_mode_from_status({"fanspeed": 6}) == "medium_high"
    assert fan_mode_from_status({}) == "auto"


def test_is_valid_temperature_rejects_disconnected_probe() -> None:
    assert is_valid_temperature(21.5) is True
    assert is_valid_temperature(TEMP_DISCONNECTED_C) is False
    assert is_valid_temperature(-50) is False
    assert is_valid_temperature(None) is False
    assert is_valid_temperature("21") is False


def test_clamp_temperature_stays_in_firmware_range() -> None:
    assert clamp_temperature(21) == 21
    assert clamp_temperature(10) == 15
    assert clamp_temperature(40) == 30
    assert clamp_temperature(None) == 21
    assert clamp_temperature("22.9") == 22
