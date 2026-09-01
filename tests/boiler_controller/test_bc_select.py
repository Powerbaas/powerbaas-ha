"""Select entity command mapping against a fake coordinator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.powerbaas.devices.boiler_controller.const import (
    BOILER_MODE_AUTO,
    BOILER_MODE_CALIBRATING,
    BOILER_MODE_OFF,
)
from custom_components.powerbaas.devices.boiler_controller.select import (
    BoilerControllerMaxHeatingWattsSelect,
    BoilerControllerModeSelect,
)


def _mode_select(*, control_mode, calibration_active=False, online=True) -> BoilerControllerModeSelect:
    coordinator = SimpleNamespace(
        data={"control_mode": control_mode, "calibration_active": calibration_active},
        device_online=online,
        async_set_control_mode=AsyncMock(),
    )
    entry = MagicMock()
    entry.entry_id = "bc_entry"
    select = object.__new__(BoilerControllerModeSelect)
    select.coordinator = coordinator
    select.config_entry = entry
    return select


def test_current_option_reflects_control_mode() -> None:
    select = _mode_select(control_mode=BOILER_MODE_AUTO)

    assert BoilerControllerModeSelect.current_option.fget(select) == BOILER_MODE_AUTO


def test_current_option_shows_calibrating_when_active() -> None:
    select = _mode_select(control_mode=BOILER_MODE_AUTO, calibration_active=True)

    assert BoilerControllerModeSelect.current_option.fget(select) == BOILER_MODE_CALIBRATING


async def test_select_option_delegates_to_coordinator() -> None:
    select = _mode_select(control_mode=BOILER_MODE_OFF)

    await BoilerControllerModeSelect.async_select_option(select, BOILER_MODE_AUTO)

    select.coordinator.async_set_control_mode.assert_awaited_once_with(BOILER_MODE_AUTO)


async def test_select_option_raises_during_calibration() -> None:
    select = _mode_select(control_mode=BOILER_MODE_OFF, calibration_active=True)

    with pytest.raises(HomeAssistantError):
        await BoilerControllerModeSelect.async_select_option(select, BOILER_MODE_AUTO)


def test_mode_select_unavailable_during_calibration() -> None:
    select = _mode_select(control_mode=BOILER_MODE_OFF, calibration_active=True)

    assert BoilerControllerModeSelect.available.fget(select) is False


def test_mode_select_unavailable_when_offline() -> None:
    select = _mode_select(control_mode=BOILER_MODE_OFF, online=False)

    assert BoilerControllerModeSelect.available.fget(select) is False


def _max_watts_select(*, max_heating_watts, online=True) -> BoilerControllerMaxHeatingWattsSelect:
    coordinator = SimpleNamespace(
        data={"max_heating_watts": max_heating_watts},
        device_online=online,
        async_set_max_heating_watts=AsyncMock(),
    )
    entry = MagicMock()
    entry.entry_id = "bc_entry"
    select = object.__new__(BoilerControllerMaxHeatingWattsSelect)
    select.coordinator = coordinator
    select.config_entry = entry
    return select


def test_max_watts_current_option() -> None:
    select = _max_watts_select(max_heating_watts=2000)

    assert BoilerControllerMaxHeatingWattsSelect.current_option.fget(select) == "2000"


async def test_max_watts_select_option_delegates() -> None:
    select = _max_watts_select(max_heating_watts=2000)

    await BoilerControllerMaxHeatingWattsSelect.async_select_option(select, "1500")

    select.coordinator.async_set_max_heating_watts.assert_awaited_once_with(1500)


def test_max_watts_unavailable_when_offline() -> None:
    select = _max_watts_select(max_heating_watts=2000, online=False)

    assert BoilerControllerMaxHeatingWattsSelect.available.fget(select) is False
