"""Tests for the bc_run_calibration/bc_cancel_calibration services.

Calibration used to be triggered from Calibrate Start/Stop button entities
(see test_bc_button.py, now removed) - it's now only reachable via these
services, so the notify-on-start/notify-on-failure/notify-on-cancel behavior
that used to live in the buttons is tested here instead.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState, current_entry
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerbaas.const import CONF_DEVICE_TYPE, DEVICE_TYPE_BOILER_CONTROLLER, DOMAIN
from custom_components.powerbaas.devices.boiler_controller import async_setup_entry
from custom_components.powerbaas.devices.boiler_controller.const import (
    CONF_DEVICE_URL,
    CONF_POWER_SENSOR,
    CONF_POWER_SENSOR_TYPE,
    POWER_SENSOR_TYPE_NET,
    SERVICE_CANCEL_CALIBRATION,
    SERVICE_RUN_CALIBRATION,
)


class _FakeResponse:
    def __init__(self, json_data: Any, status: int = 200) -> None:
        self.status = status
        self._json_data = json_data

    async def json(self, content_type=None):  # noqa: ANN001
        return self._json_data

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return False


class _FakeSession:
    """Serves queued responses in order for every .get()/.post() call."""

    def __init__(self) -> None:
        self._queue: list[Any] = []

    def queue_response(self, json_data: Any) -> None:
        self._queue.append(json_data)

    def _next(self) -> _FakeResponse:
        return _FakeResponse(self._queue.pop(0) if self._queue else {})

    def get(self, url: str, timeout=None, params=None):  # noqa: ANN001
        return self._next()

    def post(self, url: str, timeout=None, json=None):  # noqa: ANN001
        return self._next()


def _make_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="test_bc_entry_id",
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_BOILER_CONTROLLER,
            CONF_DEVICE_URL: "http://bc.local",
            CONF_POWER_SENSOR_TYPE: POWER_SENSOR_TYPE_NET,
            CONF_POWER_SENSOR: "sensor.net_power",
            "device_id": "pb-bc-test",
        },
        title="Test BC",
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    return entry


async def _setup_coordinator(hass, monkeypatch: pytest.MonkeyPatch):
    session = _FakeSession()
    for _ in range(3):
        session.queue_response({"power": 0, "heatingPercentage": 0, "maxHeatingWatts": 2000})
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.bc_client.async_get_clientsession",
        lambda _hass: session,
    )

    entry = _make_entry(hass)
    token = current_entry.set(entry)
    try:
        result = await async_setup_entry(hass, entry)
    finally:
        current_entry.reset(token)

    # Mirrors what custom_components/powerbaas/__init__.py's own
    # async_setup_entry does - _async_resolve_coordinator() looks entries up
    # from here, not from this device-level setup's return value.
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = result

    return result["coordinator"]


async def test_run_calibration_service_notifies_and_calls_coordinator(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = await _setup_coordinator(hass, monkeypatch)
    coordinator.async_run_calibration = AsyncMock()
    notify = MagicMock()
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.persistent_notification.async_create",
        notify,
    )

    await hass.services.async_call(DOMAIN, SERVICE_RUN_CALIBRATION, {}, blocking=True)

    coordinator.async_run_calibration.assert_awaited_once()
    notify.assert_called_once()
    assert "cooled down" in notify.call_args.args[1]


async def test_run_calibration_service_notifies_and_reraises_on_failure(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = await _setup_coordinator(hass, monkeypatch)
    coordinator.async_run_calibration = AsyncMock(side_effect=RuntimeError("boom"))
    notify = MagicMock()
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.persistent_notification.async_create",
        notify,
    )

    with pytest.raises(RuntimeError):
        await hass.services.async_call(DOMAIN, SERVICE_RUN_CALIBRATION, {}, blocking=True)

    # Once for the start-of-sweep instructions, once for the failure.
    assert notify.call_count == 2
    assert "boom" in notify.call_args.args[1]


async def test_cancel_calibration_service_requests_cancel_and_notifies(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = await _setup_coordinator(hass, monkeypatch)
    coordinator.async_request_calibration_cancel = AsyncMock(return_value=True)
    notify = MagicMock()
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.persistent_notification.async_create",
        notify,
    )

    await hass.services.async_call(DOMAIN, SERVICE_CANCEL_CALIBRATION, {}, blocking=True)

    coordinator.async_request_calibration_cancel.assert_awaited_once()
    notify.assert_called_once()
    assert "cancellation requested" in notify.call_args.args[1]


async def test_cancel_calibration_service_raises_when_nothing_active(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = await _setup_coordinator(hass, monkeypatch)
    coordinator.async_request_calibration_cancel = AsyncMock(return_value=False)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, SERVICE_CANCEL_CALIBRATION, {}, blocking=True)
