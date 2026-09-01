"""Calibration button command mapping against a fake coordinator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.powerbaas.devices.boiler_controller.button import (
    BoilerCalibrationButton,
    BoilerCalibrationStopButton,
)


def _button(cls, *, calibration_active: bool):
    coordinator = SimpleNamespace(
        data={"calibration_active": calibration_active},
        device_online=True,
        async_run_calibration=AsyncMock(),
        async_request_calibration_cancel=AsyncMock(return_value=True),
    )
    entry = MagicMock()
    entry.entry_id = "bc_entry"
    entry.title = "Test BC"
    created_tasks: list = []

    def _fake_create_task(coro):
        created_tasks.append(coro)
        coro.close()  # avoid "coroutine was never awaited" - not exercised here
        return MagicMock()

    button = object.__new__(cls)
    button.coordinator = coordinator
    button.config_entry = entry
    button.hass = SimpleNamespace(async_create_task=_fake_create_task)
    button._async_notify = AsyncMock()
    button._created_tasks = created_tasks
    return button


async def test_start_button_available_when_not_calibrating() -> None:
    button = _button(BoilerCalibrationButton, calibration_active=False)

    assert BoilerCalibrationButton.available.fget(button) is True


async def test_start_button_unavailable_while_calibrating() -> None:
    button = _button(BoilerCalibrationButton, calibration_active=True)

    assert BoilerCalibrationButton.available.fget(button) is False


async def test_start_button_press_raises_when_already_active() -> None:
    button = _button(BoilerCalibrationButton, calibration_active=True)

    with pytest.raises(HomeAssistantError):
        await BoilerCalibrationButton.async_press(button)


async def test_start_button_press_notifies_and_schedules_run() -> None:
    button = _button(BoilerCalibrationButton, calibration_active=False)

    await BoilerCalibrationButton.async_press(button)

    button._async_notify.assert_awaited_once()
    assert len(button._created_tasks) == 1


async def test_stop_button_available_only_while_calibrating() -> None:
    running = _button(BoilerCalibrationStopButton, calibration_active=True)
    assert BoilerCalibrationStopButton.available.fget(running) is True

    idle = _button(BoilerCalibrationStopButton, calibration_active=False)
    assert BoilerCalibrationStopButton.available.fget(idle) is False


async def test_stop_button_press_raises_when_not_active() -> None:
    button = _button(BoilerCalibrationStopButton, calibration_active=False)

    with pytest.raises(HomeAssistantError):
        await BoilerCalibrationStopButton.async_press(button)


async def test_stop_button_press_requests_cancel_and_notifies() -> None:
    button = _button(BoilerCalibrationStopButton, calibration_active=True)

    await BoilerCalibrationStopButton.async_press(button)

    button.coordinator.async_request_calibration_cancel.assert_awaited_once()
    button._async_notify.assert_awaited_once()


async def test_stop_button_press_raises_when_cancel_not_requested() -> None:
    button = _button(BoilerCalibrationStopButton, calibration_active=True)
    button.coordinator.async_request_calibration_cancel = AsyncMock(return_value=False)

    with pytest.raises(HomeAssistantError):
        await BoilerCalibrationStopButton.async_press(button)
