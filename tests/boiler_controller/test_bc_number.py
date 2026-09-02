"""Number entity command mapping against a fake coordinator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.powerbaas.devices.boiler_controller.const import (
    BOILER_MODE_AUTO,
    BOILER_MODE_MANUAL,
)
from custom_components.powerbaas.devices.boiler_controller.number import (
    BoilerControllerManualBrightnessNumber,
    BoilerControllerMinHeatingWattsNumber,
)


def _manual_number(
    *, control_mode, target_watts=0, max_heating_watts=2000, calibration_active=False, online=True
) -> BoilerControllerManualBrightnessNumber:
    coordinator = SimpleNamespace(
        data={
            "control_mode": control_mode,
            "target_watts": target_watts,
            "max_heating_watts": max_heating_watts,
            "calibration_active": calibration_active,
        },
        device_online=online,
        async_set_target_watts=AsyncMock(),
    )
    entry = MagicMock()
    entry.entry_id = "bc_entry"
    number = object.__new__(BoilerControllerManualBrightnessNumber)
    number.coordinator = coordinator
    number.config_entry = entry
    return number


def test_manual_number_value_and_max() -> None:
    number = _manual_number(control_mode=BOILER_MODE_MANUAL, target_watts=500, max_heating_watts=1500)

    assert BoilerControllerManualBrightnessNumber.native_value.fget(number) == 500
    assert BoilerControllerManualBrightnessNumber.native_max_value.fget(number) == 1500


async def test_manual_number_set_value_delegates() -> None:
    number = _manual_number(control_mode=BOILER_MODE_MANUAL)

    await BoilerControllerManualBrightnessNumber.async_set_native_value(number, 300)

    number.coordinator.async_set_target_watts.assert_awaited_once_with(300)


async def test_manual_number_set_value_raises_during_calibration() -> None:
    number = _manual_number(control_mode=BOILER_MODE_MANUAL, calibration_active=True)

    with pytest.raises(HomeAssistantError):
        await BoilerControllerManualBrightnessNumber.async_set_native_value(number, 300)


def test_manual_number_available_in_any_mode() -> None:
    number = _manual_number(control_mode=BOILER_MODE_AUTO)

    assert BoilerControllerManualBrightnessNumber.available.fget(number) is True


async def test_manual_number_set_value_raises_outside_manual_mode() -> None:
    number = _manual_number(control_mode=BOILER_MODE_AUTO)

    with pytest.raises(HomeAssistantError):
        await BoilerControllerManualBrightnessNumber.async_set_native_value(number, 300)


def test_manual_number_unavailable_when_offline() -> None:
    number = _manual_number(control_mode=BOILER_MODE_MANUAL, online=False)

    assert BoilerControllerManualBrightnessNumber.available.fget(number) is False


def _min_number(
    *, control_mode, min_heating_watts=0, max_heating_watts=2000, calibration_active=False, online=True
) -> BoilerControllerMinHeatingWattsNumber:
    coordinator = SimpleNamespace(
        data={
            "control_mode": control_mode,
            "min_heating_watts": min_heating_watts,
            "max_heating_watts": max_heating_watts,
            "calibration_active": calibration_active,
        },
        device_online=online,
        async_set_min_heating_watts=AsyncMock(),
    )
    entry = MagicMock()
    entry.entry_id = "bc_entry"
    number = object.__new__(BoilerControllerMinHeatingWattsNumber)
    number.coordinator = coordinator
    number.config_entry = entry
    return number


def test_min_number_value_and_max() -> None:
    number = _min_number(control_mode=BOILER_MODE_AUTO, min_heating_watts=300, max_heating_watts=1500)

    assert BoilerControllerMinHeatingWattsNumber.native_value.fget(number) == 300
    assert BoilerControllerMinHeatingWattsNumber.native_max_value.fget(number) == 1500


async def test_min_number_set_value_delegates() -> None:
    number = _min_number(control_mode=BOILER_MODE_AUTO)

    await BoilerControllerMinHeatingWattsNumber.async_set_native_value(number, 400)

    number.coordinator.async_set_min_heating_watts.assert_awaited_once_with(400)


def test_min_number_available_only_in_auto_mode() -> None:
    number = _min_number(control_mode=BOILER_MODE_MANUAL)

    assert BoilerControllerMinHeatingWattsNumber.available.fget(number) is False


def test_min_number_unavailable_when_offline() -> None:
    number = _min_number(control_mode=BOILER_MODE_AUTO, online=False)

    assert BoilerControllerMinHeatingWattsNumber.available.fget(number) is False
