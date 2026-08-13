"""Scenario tests for BoilerController's pure-logic methods.

BoilerController itself is heavyweight to construct in full (a real
ConfigEntry wired through Home Assistant's config_entries machinery), but the
methods under test here only touch a well-defined set of `self.*`
attributes. We bind the real methods onto a bare `object.__new__`-constructed
controller and set exactly the state they read/write - this exercises the
real dispatch/surplus/offline-detection logic without the unrelated setup
cost (mirrors Zendure-HA's ZendureManager harness pattern).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.powerbaas.devices.boiler_controller.const import (
    BOILER_MODE_AUTO,
    BOILER_MODE_MANUAL,
    BOILER_MODE_OFF,
    BOILER_MODE_ON,
    POWER_SENSOR_TYPE_NET,
    POWER_SENSOR_TYPE_SPLIT,
)
from custom_components.powerbaas.devices.boiler_controller.controller import BoilerController


class _FakeState:
    def __init__(self, state: str, unit: str | None = None) -> None:
        self.state = state
        self.attributes = {"unit_of_measurement": unit} if unit else {}


class _FakeHass:
    """Hass stand-in real enough for async_dispatcher_send/async_update_entry to no-op safely."""

    def __init__(self, states: dict[str, _FakeState] | None = None) -> None:
        self.data: dict[str, Any] = {}
        self._states = states or {}
        self.states = SimpleNamespace(get=self._states.get)
        self.config_entries = SimpleNamespace(async_update_entry=lambda *a, **k: None)

    def verify_event_loop_thread(self, *_args: Any, **_kwargs: Any) -> None:
        """No-op: async_dispatcher_send() calls this to guard against cross-thread use."""


class _FakeBCClient:
    """Records outgoing BCClient calls instead of doing real HTTP."""

    def __init__(self) -> None:
        self.target_watts_calls: list[int] = []
        self.heating_percentage_calls: list[int] = []
        self.status: dict | None = {}
        self.calibration_states: list[str] = []
        self.calibration_run_result = True

    async def async_set_target_watts(self, watts: int) -> bool:
        self.target_watts_calls.append(watts)
        return True

    async def async_set_heating_percentage(self, percentage: int) -> bool:
        self.heating_percentage_calls.append(percentage)
        return True

    async def async_get_status(self) -> dict | None:
        return self.status

    async def async_get_system(self) -> dict | None:
        return None

    async def async_calibration_run(self) -> bool:
        return self.calibration_run_result

    async def async_calibration_stop(self) -> bool:
        return True

    async def async_get_calibration(self) -> dict | None:
        state = self.calibration_states.pop(0) if self.calibration_states else "idle"
        return {"run": {"state": state}}


def _make_controller(
    *,
    device_client: _FakeBCClient | None = None,
    control_mode: str = BOILER_MODE_AUTO,
    max_heating_watts: int = 2000,
    min_heating_watts: int = 0,
    manual_watts: int = 0,
    power_sensor_type: str = POWER_SENSOR_TYPE_NET,
    states: dict[str, _FakeState] | None = None,
    hass: Any = None,
) -> BoilerController:
    controller = object.__new__(BoilerController)
    controller.hass = hass if hass is not None else _FakeHass(states)
    controller.config_entry = SimpleNamespace(
        entry_id="entry1", title="Test BC", options={}, data={}
    )
    controller.device_client = device_client or _FakeBCClient()
    controller._control_mode = control_mode
    controller._max_heating_watts = max_heating_watts
    controller._min_heating_watts = min_heating_watts
    controller._manual_watts = manual_watts
    controller.power_sensor_type = power_sensor_type
    if power_sensor_type == POWER_SENSOR_TYPE_SPLIT:
        controller.power_sensor_id = None
        controller.return_sensor_id = "sensor.return_power"
        controller.usage_sensor_id = "sensor.usage_power"
    else:
        controller.power_sensor_id = "sensor.net_power"
        controller.return_sensor_id = None
        controller.usage_sensor_id = None
    controller._device_status = None
    controller._system_status = None
    controller._current_dimmer_percentage = None
    controller._calibration_active = False
    controller._calibration_cancel_requested = False
    controller._calibration_previous_mode = None
    controller._calibration_lock = asyncio.Lock()
    controller._last_power_value = None
    controller._last_auto_update = None
    controller._last_control_update = None
    controller._consecutive_poll_failures = 0
    controller._device_online = True
    controller._polling_suspended = False
    controller._offline_issue_id = "boiler_controller_offline_entry1"
    controller._dispatcher_signal = "sig_status"
    controller._mode_signal = "sig_mode"
    controller._manual_watts_signal = "sig_manual_watts"
    controller._calibration_signal = "sig_calibration"
    controller._max_heating_watts_signal = "sig_max_watts"
    controller._min_heating_watts_signal = "sig_min_watts"
    controller._missing_sensor_log = {}
    return controller


# ---------------------------------------------------------------------------
# _compute_surplus
# ---------------------------------------------------------------------------


def test_compute_surplus_net_mode_is_negated() -> None:
    """Net mode: sensor is negative when exporting, surplus should be positive."""
    controller = _make_controller(
        power_sensor_type=POWER_SENSOR_TYPE_NET,
        states={"sensor.net_power": _FakeState("-500", "W")},
    )

    assert controller._compute_surplus() == 500.0


def test_compute_surplus_split_mode_is_return_minus_usage() -> None:
    controller = _make_controller(
        power_sensor_type=POWER_SENSOR_TYPE_SPLIT,
        states={
            "sensor.return_power": _FakeState("800", "W"),
            "sensor.usage_power": _FakeState("300", "W"),
        },
    )

    assert controller._compute_surplus() == 500.0


def test_compute_surplus_normalizes_kw_to_watts() -> None:
    controller = _make_controller(
        power_sensor_type=POWER_SENSOR_TYPE_NET,
        states={"sensor.net_power": _FakeState("-0.5", "kW")},
    )

    assert controller._compute_surplus() == 500.0


@pytest.mark.parametrize("sensor_state", ["unknown", "unavailable", "none"])
def test_compute_surplus_none_when_sensor_unavailable(sensor_state: str) -> None:
    controller = _make_controller(
        power_sensor_type=POWER_SENSOR_TYPE_NET,
        states={"sensor.net_power": _FakeState(sensor_state, "W")},
    )

    assert controller._compute_surplus() is None


def test_compute_surplus_none_when_sensor_missing() -> None:
    controller = _make_controller(power_sensor_type=POWER_SENSOR_TYPE_NET, states={})

    assert controller._compute_surplus() is None


def test_compute_surplus_split_mode_none_when_one_sensor_missing() -> None:
    controller = _make_controller(
        power_sensor_type=POWER_SENSOR_TYPE_SPLIT,
        states={"sensor.return_power": _FakeState("800", "W")},
    )

    assert controller._compute_surplus() is None


# ---------------------------------------------------------------------------
# _async_update dispatch per control_mode
# ---------------------------------------------------------------------------


async def test_async_update_off_mode_sets_zero_percent() -> None:
    controller = _make_controller(control_mode=BOILER_MODE_OFF)

    await controller._async_update()

    assert controller.device_client.heating_percentage_calls == [0]
    assert controller.device_client.target_watts_calls == []


async def test_async_update_on_mode_sets_full_percent() -> None:
    controller = _make_controller(control_mode=BOILER_MODE_ON)

    await controller._async_update()

    assert controller.device_client.heating_percentage_calls == [100]


async def test_async_update_manual_mode_applies_manual_watts() -> None:
    controller = _make_controller(control_mode=BOILER_MODE_MANUAL, manual_watts=750)

    await controller._async_update()

    assert controller.device_client.target_watts_calls == [750]


async def test_async_update_auto_mode_combines_boiler_draw_and_surplus() -> None:
    controller = _make_controller(
        control_mode=BOILER_MODE_AUTO,
        max_heating_watts=2000,
        states={"sensor.net_power": _FakeState("-300", "W")},  # exporting 300W
    )
    controller._device_status = {"power": 400}  # boiler currently drawing 400W

    await controller._async_update()

    # available = boiler_watts(400) + surplus(300) = 700
    assert controller.device_client.target_watts_calls == [700]
    assert controller._last_power_value == 300.0


async def test_async_update_auto_mode_clamps_to_max_heating_watts() -> None:
    controller = _make_controller(
        control_mode=BOILER_MODE_AUTO,
        max_heating_watts=500,
        states={"sensor.net_power": _FakeState("-1000", "W")},
    )
    controller._device_status = {"power": 400}

    await controller._async_update()

    assert controller.device_client.target_watts_calls == [500]


async def test_async_update_auto_mode_enforces_min_heating_watts_floor() -> None:
    controller = _make_controller(
        control_mode=BOILER_MODE_AUTO,
        max_heating_watts=2000,
        min_heating_watts=300,
        states={"sensor.net_power": _FakeState("1000", "W")},  # importing -> surplus negative
    )
    controller._device_status = {"power": 0}

    await controller._async_update()

    assert controller.device_client.target_watts_calls == [300]


async def test_async_update_auto_mode_skips_when_sensor_unreadable() -> None:
    controller = _make_controller(control_mode=BOILER_MODE_AUTO, states={})

    await controller._async_update()

    assert controller.device_client.target_watts_calls == []


async def test_async_update_skips_while_calibration_active() -> None:
    controller = _make_controller(control_mode=BOILER_MODE_ON)
    controller._calibration_active = True

    await controller._async_update()

    assert controller.device_client.heating_percentage_calls == []


# ---------------------------------------------------------------------------
# _set_heating_percentage dedup + clamping
# ---------------------------------------------------------------------------


async def test_set_heating_percentage_dedupes_unchanged_value() -> None:
    controller = _make_controller()
    controller._current_dimmer_percentage = 50

    await controller._set_heating_percentage(50)

    assert controller.device_client.heating_percentage_calls == []


async def test_set_heating_percentage_clamps_out_of_range_values() -> None:
    controller = _make_controller()

    await controller._set_heating_percentage(150)

    assert controller.device_client.heating_percentage_calls == [100]
    assert controller._current_dimmer_percentage == 100


# ---------------------------------------------------------------------------
# async_set_control_mode / async_set_manual_watts / async_set_min_heating_watts
# ---------------------------------------------------------------------------


async def test_async_set_control_mode_rejects_unknown_mode() -> None:
    controller = _make_controller(control_mode=BOILER_MODE_OFF)

    with pytest.raises(ValueError):
        await controller.async_set_control_mode("bogus")


async def test_async_set_control_mode_raises_during_calibration() -> None:
    controller = _make_controller(control_mode=BOILER_MODE_OFF)
    controller._calibration_active = True

    with pytest.raises(RuntimeError):
        await controller.async_set_control_mode(BOILER_MODE_AUTO)


async def test_async_set_control_mode_noop_when_unchanged() -> None:
    controller = _make_controller(control_mode=BOILER_MODE_OFF)

    await controller.async_set_control_mode(BOILER_MODE_OFF)

    # _async_update would have fired a heating-percentage call for OFF mode
    # if the mode change had actually been processed.
    assert controller.device_client.heating_percentage_calls == []


async def test_async_set_manual_watts_clamps_to_max() -> None:
    controller = _make_controller(control_mode=BOILER_MODE_MANUAL, max_heating_watts=1000)

    await controller.async_set_manual_watts(5000)

    assert controller._manual_watts == 1000
    assert controller.device_client.target_watts_calls == [1000]


async def test_async_set_manual_watts_raises_during_calibration() -> None:
    controller = _make_controller(control_mode=BOILER_MODE_MANUAL)
    controller._calibration_active = True

    with pytest.raises(RuntimeError):
        await controller.async_set_manual_watts(500)


async def test_async_set_min_heating_watts_clamps_to_max() -> None:
    controller = _make_controller(max_heating_watts=1000, min_heating_watts=0)

    await controller.async_set_min_heating_watts(5000)

    assert controller._min_heating_watts == 1000


# ---------------------------------------------------------------------------
# _update_cached_max_heating_watts
# ---------------------------------------------------------------------------


def test_update_cached_max_heating_watts_syncs_from_device_status() -> None:
    controller = _make_controller(max_heating_watts=2000, min_heating_watts=0)

    controller._update_cached_max_heating_watts({"maxHeatingWatts": 1500})

    assert controller._max_heating_watts == 1500


def test_update_cached_max_heating_watts_clamps_min_down_when_it_exceeds_new_max() -> None:
    controller = _make_controller(max_heating_watts=2000, min_heating_watts=1800)

    controller._update_cached_max_heating_watts({"maxHeatingWatts": 1000})

    assert controller._max_heating_watts == 1000
    assert controller._min_heating_watts == 1000


# ---------------------------------------------------------------------------
# offline detection (_register_poll_failure / _handle_status_success)
# ---------------------------------------------------------------------------


async def test_register_poll_failure_flips_offline_after_threshold(hass) -> None:
    from custom_components.powerbaas.const import OFFLINE_AFTER_CONSECUTIVE_FAILURES

    controller = _make_controller()
    controller.hass = hass

    for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES - 1):
        controller._register_poll_failure()
        assert controller._device_online is True

    controller._register_poll_failure()

    assert controller._device_online is False
    assert controller._device_status is None


async def test_handle_status_success_resets_failure_count_and_online_state(hass) -> None:
    from custom_components.powerbaas.const import OFFLINE_AFTER_CONSECUTIVE_FAILURES

    controller = _make_controller()
    controller.hass = hass

    for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
        controller._register_poll_failure()
    assert controller._device_online is False

    controller._handle_status_success({"power": 100})

    assert controller._device_online is True
    assert controller._consecutive_poll_failures == 0
    assert controller._device_status == {"power": 100}


# ---------------------------------------------------------------------------
# async_run_calibration state machine
# ---------------------------------------------------------------------------


async def test_run_calibration_completes_on_done_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.controller.asyncio.sleep",
        _instant_sleep,
    )
    client = _FakeBCClient()
    client.calibration_states = ["running", "done"]
    controller = _make_controller(control_mode=BOILER_MODE_OFF, device_client=client)

    await controller.async_run_calibration()

    assert controller._calibration_active is False
    assert controller._control_mode == BOILER_MODE_OFF


async def test_run_calibration_switches_to_off_during_run_then_restores_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.controller.asyncio.sleep",
        _instant_sleep,
    )
    client = _FakeBCClient()
    client.calibration_states = ["done"]
    controller = _make_controller(control_mode=BOILER_MODE_AUTO, device_client=client)

    await controller.async_run_calibration()

    # Auto mode isn't OFF/MANUAL, so calibration forced it to OFF for the
    # duration and restored AUTO afterwards.
    assert controller._control_mode == BOILER_MODE_AUTO


async def test_run_calibration_rejects_concurrent_runs() -> None:
    """A run already holding `_calibration_lock` must reject a second call.

    Driving this through real task scheduling would be timing-dependent (with
    `asyncio.sleep` stubbed to a no-op, a first run with no pending device
    state can race to completion before a second call gets scheduled) - so
    the lock is held directly instead.
    """
    controller = _make_controller(control_mode=BOILER_MODE_OFF)

    await controller._calibration_lock.acquire()
    try:
        with pytest.raises(RuntimeError):
            await controller.async_run_calibration()
    finally:
        controller._calibration_lock.release()


async def _instant_sleep(_seconds: float) -> None:
    return None
