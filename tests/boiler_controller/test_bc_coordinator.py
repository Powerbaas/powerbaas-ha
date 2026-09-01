"""Scenario tests for BoilerControllerCoordinator's pure-logic methods.

BoilerControllerCoordinator is heavyweight to construct in full (a real
ConfigEntry wired through Home Assistant's config_entries machinery), but the
methods under test here only touch a well-defined set of `self.*`
attributes/`self.data` keys. We bind the real methods onto a bare
`object.__new__`-constructed coordinator and set exactly the state they
read/write - this exercises the real dispatch/surplus/offline-detection
logic without the unrelated setup cost.

`async_request_refresh()` (HA's built-in debounced refresh, used in place of
the old `_async_refresh_device_status()`) is stubbed out here since it drags
in a lot of unrelated DataUpdateCoordinator scheduling machinery that these
pure-logic tests don't exercise - it's covered for real via the `hass`
fixture in test_bc_setup.py.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from custom_components.powerbaas.devices.boiler_controller.const import (
    BOILER_MODE_AUTO,
    BOILER_MODE_MANUAL,
    BOILER_MODE_OFF,
    BOILER_MODE_ON,
    POWER_SENSOR_TYPE_NET,
    POWER_SENSOR_TYPE_SPLIT,
)
from custom_components.powerbaas.devices.boiler_controller.coordinator import (
    BoilerControllerCoordinator,
)

_LOGGER = logging.getLogger("test_bc_coordinator")


class _FakeState:
    def __init__(self, state: str, unit: str | None = None) -> None:
        self.state = state
        self.attributes = {"unit_of_measurement": unit} if unit else {}


class _FakeHass:
    """Hass stand-in real enough for async_update_entry to no-op safely."""

    def __init__(self, states: dict[str, _FakeState] | None = None) -> None:
        self.data: dict[str, Any] = {}
        self._states = states or {}
        self.states = SimpleNamespace(get=self._states.get)
        self.config_entries = SimpleNamespace(async_update_entry=lambda *a, **k: None)


class _FakeBCClient:
    """Records outgoing BCClient calls instead of doing real HTTP."""

    def __init__(self) -> None:
        self.target_watts_calls: list[int] = []
        self.heating_percentage_calls: list[int] = []
        self.status: dict | None = {}
        self.calibration_states: list[str] = []
        self.calibration_run_result = True
        self.ssr_calls: list[bool] = []
        self.ssr_result: bool | None = True

    async def async_set_target_watts(self, watts: int) -> bool:
        self.target_watts_calls.append(watts)
        return True

    async def async_set_heating_percentage(self, percentage: int) -> bool:
        self.heating_percentage_calls.append(percentage)
        return True

    async def async_get_status(self) -> dict | None:
        return self.status

    async def async_set_ssr(self, on: bool) -> bool | None:
        self.ssr_calls.append(on)
        return self.ssr_result

    async def async_get_system(self) -> dict | None:
        return None

    async def async_calibration_run(self) -> bool:
        return self.calibration_run_result

    async def async_calibration_stop(self) -> bool:
        return True

    async def async_get_calibration(self) -> dict | None:
        state = self.calibration_states.pop(0) if self.calibration_states else "idle"
        return {"run": {"state": state}}


def _make_coordinator(
    *,
    device_client: _FakeBCClient | None = None,
    control_mode: str = BOILER_MODE_AUTO,
    max_heating_watts: int = 2000,
    min_heating_watts: int = 0,
    manual_watts: int = 0,
    power_sensor_type: str = POWER_SENSOR_TYPE_NET,
    states: dict[str, _FakeState] | None = None,
    hass: Any = None,
) -> BoilerControllerCoordinator:
    coordinator = object.__new__(BoilerControllerCoordinator)
    coordinator.hass = hass if hass is not None else _FakeHass(states)
    coordinator.logger = _LOGGER
    coordinator.name = "test_bc"
    coordinator.config_entry = SimpleNamespace(
        entry_id="entry1", title="Test BC", options={}, data={}
    )
    coordinator.device_client = device_client or _FakeBCClient()
    coordinator.data = {
        "status": None,
        "system": None,
        "control_mode": control_mode,
        "manual_watts": manual_watts,
        "max_heating_watts": max_heating_watts,
        "min_heating_watts": min_heating_watts,
        "calibration_active": False,
    }
    coordinator.power_sensor_type = power_sensor_type
    if power_sensor_type == POWER_SENSOR_TYPE_SPLIT:
        coordinator.power_sensor_id = None
        coordinator.return_sensor_id = "sensor.return_power"
        coordinator.usage_sensor_id = "sensor.usage_power"
    else:
        coordinator.power_sensor_id = "sensor.net_power"
        coordinator.return_sensor_id = None
        coordinator.usage_sensor_id = None
    coordinator._current_dimmer_percentage = None
    coordinator._calibration_cancel_requested = False
    coordinator._calibration_previous_mode = None
    coordinator._calibration_lock = asyncio.Lock()
    coordinator._last_power_value = None
    coordinator._last_auto_update = None
    coordinator._last_control_update = None
    coordinator._consecutive_failures = 0
    coordinator.device_online = True
    coordinator._offline_issue_id = "boiler_controller_offline_entry1"
    coordinator._missing_sensor_log = {}
    # Minimal DataUpdateCoordinator internals needed by
    # async_set_updated_data()/async_update_listeners() (bypassed __init__).
    coordinator._unsub_refresh = None
    coordinator._debounced_refresh = SimpleNamespace(async_cancel=lambda: None)
    coordinator._listeners = {}
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


# ---------------------------------------------------------------------------
# _compute_surplus
# ---------------------------------------------------------------------------


def test_compute_surplus_net_mode_is_negated() -> None:
    """Net mode: sensor is negative when exporting, surplus should be positive."""
    coordinator = _make_coordinator(
        power_sensor_type=POWER_SENSOR_TYPE_NET,
        states={"sensor.net_power": _FakeState("-500", "W")},
    )

    assert coordinator._compute_surplus() == 500.0


def test_compute_surplus_split_mode_is_return_minus_usage() -> None:
    coordinator = _make_coordinator(
        power_sensor_type=POWER_SENSOR_TYPE_SPLIT,
        states={
            "sensor.return_power": _FakeState("800", "W"),
            "sensor.usage_power": _FakeState("300", "W"),
        },
    )

    assert coordinator._compute_surplus() == 500.0


def test_compute_surplus_normalizes_kw_to_watts() -> None:
    coordinator = _make_coordinator(
        power_sensor_type=POWER_SENSOR_TYPE_NET,
        states={"sensor.net_power": _FakeState("-0.5", "kW")},
    )

    assert coordinator._compute_surplus() == 500.0


@pytest.mark.parametrize("sensor_state", ["unknown", "unavailable", "none"])
def test_compute_surplus_none_when_sensor_unavailable(sensor_state: str) -> None:
    coordinator = _make_coordinator(
        power_sensor_type=POWER_SENSOR_TYPE_NET,
        states={"sensor.net_power": _FakeState(sensor_state, "W")},
    )

    assert coordinator._compute_surplus() is None


def test_compute_surplus_none_when_sensor_missing() -> None:
    coordinator = _make_coordinator(power_sensor_type=POWER_SENSOR_TYPE_NET, states={})

    assert coordinator._compute_surplus() is None


def test_compute_surplus_split_mode_none_when_one_sensor_missing() -> None:
    coordinator = _make_coordinator(
        power_sensor_type=POWER_SENSOR_TYPE_SPLIT,
        states={"sensor.return_power": _FakeState("800", "W")},
    )

    assert coordinator._compute_surplus() is None


# ---------------------------------------------------------------------------
# _async_update dispatch per control_mode
# ---------------------------------------------------------------------------


async def test_async_update_off_mode_sets_zero_percent() -> None:
    coordinator = _make_coordinator(control_mode=BOILER_MODE_OFF)

    await coordinator._async_update()

    assert coordinator.device_client.heating_percentage_calls == [0]
    assert coordinator.device_client.target_watts_calls == []


async def test_async_update_on_mode_sets_full_percent() -> None:
    coordinator = _make_coordinator(control_mode=BOILER_MODE_ON)

    await coordinator._async_update()

    assert coordinator.device_client.heating_percentage_calls == [100]


async def test_async_update_manual_mode_applies_manual_watts() -> None:
    coordinator = _make_coordinator(control_mode=BOILER_MODE_MANUAL, manual_watts=750)

    await coordinator._async_update()

    assert coordinator.device_client.target_watts_calls == [750]


async def test_async_update_auto_mode_combines_boiler_draw_and_surplus() -> None:
    coordinator = _make_coordinator(
        control_mode=BOILER_MODE_AUTO,
        max_heating_watts=2000,
        states={"sensor.net_power": _FakeState("-300", "W")},  # exporting 300W
    )
    coordinator.data = {**coordinator.data, "status": {"power": 400}}  # boiler drawing 400W

    await coordinator._async_update()

    # available = boiler_watts(400) + surplus(300) = 700
    assert coordinator.device_client.target_watts_calls == [700]
    assert coordinator._last_power_value == 300.0


async def test_async_update_auto_mode_clamps_to_max_heating_watts() -> None:
    coordinator = _make_coordinator(
        control_mode=BOILER_MODE_AUTO,
        max_heating_watts=500,
        states={"sensor.net_power": _FakeState("-1000", "W")},
    )
    coordinator.data = {**coordinator.data, "status": {"power": 400}}

    await coordinator._async_update()

    assert coordinator.device_client.target_watts_calls == [500]


async def test_async_update_auto_mode_enforces_min_heating_watts_floor() -> None:
    coordinator = _make_coordinator(
        control_mode=BOILER_MODE_AUTO,
        max_heating_watts=2000,
        min_heating_watts=300,
        states={"sensor.net_power": _FakeState("1000", "W")},  # importing -> surplus negative
    )
    coordinator.data = {**coordinator.data, "status": {"power": 0}}

    await coordinator._async_update()

    assert coordinator.device_client.target_watts_calls == [300]


async def test_async_update_auto_mode_skips_when_sensor_unreadable() -> None:
    coordinator = _make_coordinator(control_mode=BOILER_MODE_AUTO, states={})

    await coordinator._async_update()

    assert coordinator.device_client.target_watts_calls == []


async def test_async_update_skips_while_calibration_active() -> None:
    coordinator = _make_coordinator(control_mode=BOILER_MODE_ON)
    coordinator.data = {**coordinator.data, "calibration_active": True}

    await coordinator._async_update()

    assert coordinator.device_client.heating_percentage_calls == []


# ---------------------------------------------------------------------------
# _set_heating_percentage dedup + clamping
# ---------------------------------------------------------------------------


async def test_set_heating_percentage_dedupes_unchanged_value() -> None:
    coordinator = _make_coordinator()
    coordinator._current_dimmer_percentage = 50

    await coordinator._set_heating_percentage(50)

    assert coordinator.device_client.heating_percentage_calls == []


async def test_set_heating_percentage_clamps_out_of_range_values() -> None:
    coordinator = _make_coordinator()

    await coordinator._set_heating_percentage(150)

    assert coordinator.device_client.heating_percentage_calls == [100]
    assert coordinator._current_dimmer_percentage == 100


# ---------------------------------------------------------------------------
# async_set_control_mode / async_set_manual_watts / async_set_min_heating_watts
# ---------------------------------------------------------------------------


async def test_async_set_control_mode_rejects_unknown_mode() -> None:
    coordinator = _make_coordinator(control_mode=BOILER_MODE_OFF)

    with pytest.raises(ValueError):
        await coordinator.async_set_control_mode("bogus")


async def test_async_set_control_mode_raises_during_calibration() -> None:
    coordinator = _make_coordinator(control_mode=BOILER_MODE_OFF)
    coordinator.data = {**coordinator.data, "calibration_active": True}

    with pytest.raises(RuntimeError):
        await coordinator.async_set_control_mode(BOILER_MODE_AUTO)


async def test_async_set_control_mode_noop_when_unchanged() -> None:
    coordinator = _make_coordinator(control_mode=BOILER_MODE_OFF)

    await coordinator.async_set_control_mode(BOILER_MODE_OFF)

    # _async_update would have fired a heating-percentage call for OFF mode
    # if the mode change had actually been processed.
    assert coordinator.device_client.heating_percentage_calls == []


async def test_async_set_manual_watts_clamps_to_max() -> None:
    coordinator = _make_coordinator(control_mode=BOILER_MODE_MANUAL, max_heating_watts=1000)

    await coordinator.async_set_manual_watts(5000)

    assert coordinator.data["manual_watts"] == 1000
    assert coordinator.device_client.target_watts_calls == [1000]


async def test_async_set_manual_watts_raises_during_calibration() -> None:
    coordinator = _make_coordinator(control_mode=BOILER_MODE_MANUAL)
    coordinator.data = {**coordinator.data, "calibration_active": True}

    with pytest.raises(RuntimeError):
        await coordinator.async_set_manual_watts(500)


async def test_async_set_min_heating_watts_clamps_to_max() -> None:
    coordinator = _make_coordinator(max_heating_watts=1000, min_heating_watts=0)

    await coordinator.async_set_min_heating_watts(5000)

    assert coordinator.data["min_heating_watts"] == 1000


async def test_async_set_ssr_applies_device_confirmed_state_without_refresh() -> None:
    """async_set_ssr must not depend on async_request_refresh() to reflect the
    new state: that goes through DataUpdateCoordinator's debounced refresh,
    which can be deferred behind an in-flight periodic poll and cause the
    switch to revert to its old state before flipping again once the
    deferred refresh finally runs. Applying the device's confirmed response
    directly via async_set_updated_data() avoids that race.
    """
    device_client = _FakeBCClient()
    device_client.status = {"ssr": {"on": False}}
    device_client.ssr_result = True
    coordinator = _make_coordinator(device_client=device_client)
    coordinator.data = {**coordinator.data, "status": {"ssr": {"on": False}}}

    await coordinator.async_set_ssr(True)

    assert device_client.ssr_calls == [True]
    assert coordinator.data["status"]["ssr"]["on"] is True
    coordinator.async_request_refresh.assert_not_awaited()


async def test_async_set_ssr_noop_when_device_confirmation_fails() -> None:
    device_client = _FakeBCClient()
    device_client.ssr_result = None
    coordinator = _make_coordinator(device_client=device_client)
    coordinator.data = {**coordinator.data, "status": {"ssr": {"on": False}}}

    await coordinator.async_set_ssr(True)

    assert coordinator.data["status"]["ssr"]["on"] is False


# ---------------------------------------------------------------------------
# _apply_max_heating_watts_from_status
# ---------------------------------------------------------------------------


def test_apply_max_heating_watts_from_status_syncs_from_device_status() -> None:
    coordinator = _make_coordinator(max_heating_watts=2000, min_heating_watts=0)
    data = dict(coordinator.data)

    coordinator._apply_max_heating_watts_from_status(data, {"maxHeatingWatts": 1500})

    assert data["max_heating_watts"] == 1500


def test_apply_max_heating_watts_from_status_clamps_min_down_when_it_exceeds_new_max() -> None:
    coordinator = _make_coordinator(max_heating_watts=2000, min_heating_watts=1800)
    data = dict(coordinator.data)

    coordinator._apply_max_heating_watts_from_status(data, {"maxHeatingWatts": 1000})

    assert data["max_heating_watts"] == 1000
    assert data["min_heating_watts"] == 1000


# ---------------------------------------------------------------------------
# offline detection (_register_failure / _register_success)
# ---------------------------------------------------------------------------


async def test_register_failure_flips_offline_after_threshold(hass) -> None:
    from custom_components.powerbaas.const import OFFLINE_AFTER_CONSECUTIVE_FAILURES

    coordinator = _make_coordinator()
    coordinator.hass = hass

    for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES - 1):
        coordinator._register_failure()
        assert coordinator.device_online is True

    coordinator._register_failure()

    assert coordinator.device_online is False
    assert coordinator.data["status"] is None
    assert coordinator.data["system"] is None


async def test_register_success_resets_failure_count_and_online_state(hass) -> None:
    from custom_components.powerbaas.const import OFFLINE_AFTER_CONSECUTIVE_FAILURES

    coordinator = _make_coordinator()
    coordinator.hass = hass

    for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
        coordinator._register_failure()
    assert coordinator.device_online is False

    coordinator._register_success()

    assert coordinator.device_online is True
    assert coordinator._consecutive_failures == 0


# ---------------------------------------------------------------------------
# async_run_calibration state machine
# ---------------------------------------------------------------------------


async def test_run_calibration_completes_on_done_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.coordinator.asyncio.sleep",
        _instant_sleep,
    )
    client = _FakeBCClient()
    client.calibration_states = ["running", "done"]
    coordinator = _make_coordinator(control_mode=BOILER_MODE_OFF, device_client=client)

    await coordinator.async_run_calibration()

    assert coordinator.data["calibration_active"] is False
    assert coordinator.data["control_mode"] == BOILER_MODE_OFF


async def test_run_calibration_switches_to_off_during_run_then_restores_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.coordinator.asyncio.sleep",
        _instant_sleep,
    )
    client = _FakeBCClient()
    client.calibration_states = ["done"]
    coordinator = _make_coordinator(control_mode=BOILER_MODE_AUTO, device_client=client)

    await coordinator.async_run_calibration()

    # Auto mode isn't OFF/MANUAL, so calibration forced it to OFF for the
    # duration and restored AUTO afterwards.
    assert coordinator.data["control_mode"] == BOILER_MODE_AUTO


async def test_run_calibration_rejects_concurrent_runs() -> None:
    """A run already holding `_calibration_lock` must reject a second call.

    Driving this through real task scheduling would be timing-dependent (with
    `asyncio.sleep` stubbed to a no-op, a first run with no pending device
    state can race to completion before a second call gets scheduled) - so
    the lock is held directly instead.
    """
    coordinator = _make_coordinator(control_mode=BOILER_MODE_OFF)

    await coordinator._calibration_lock.acquire()
    try:
        with pytest.raises(RuntimeError):
            await coordinator.async_run_calibration()
    finally:
        coordinator._calibration_lock.release()


async def _instant_sleep(_seconds: float) -> None:
    return None
