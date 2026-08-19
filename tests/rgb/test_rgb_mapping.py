"""Unit tests for Powerbaas RGB mapping helpers."""

from custom_components.powerbaas.devices.rgb.const import (
    is_standalone,
    is_valid_power_usage,
)


def test_is_standalone() -> None:
    assert is_standalone({"mode": "Standalone"}) is True
    assert is_standalone({"mode": "Powerbaas"}) is False
    assert is_standalone({}) is False
    assert is_standalone(None) is False


def test_is_valid_power_usage() -> None:
    assert is_valid_power_usage(0) is True
    assert is_valid_power_usage(1234) is True
    assert is_valid_power_usage(-1) is False
    assert is_valid_power_usage(None) is False
    assert is_valid_power_usage("nope") is False
