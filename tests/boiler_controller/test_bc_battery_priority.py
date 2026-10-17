"""Battery priority: Auto mode only gives the boiler what a home battery can't take.

Scenarios mirror docs/boiler-controller.md's "Battery priority" (PV 1200 W,
battery max charge 800 W).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.powerbaas.devices.boiler_controller.const import (
    BATTERY_SENSOR_TYPE_NET,
    BATTERY_SENSOR_TYPE_SPLIT,
    BATTERY_STALL_RECHECK_SECONDS,
    BATTERY_STALL_SECONDS,
    BOILER_MODE_AUTO,
    BOILER_MODE_OFF,
)

from tests.boiler_controller.test_bc_coordinator import _FakeState, _make_coordinator

NOW = dt_util.utcnow()


def _battery_coordinator(
    *,
    grid: str,
    battery: str,
    soc: str | None = "60",
    boiler_watts: float = 0,
    margin: float = 0,
    split: tuple[str, str] | None = None,
    charge_negative: bool = False,
):
    states = {"sensor.net_power": _FakeState(grid, "W")}
    if soc is not None:
        states["sensor.battery_soc"] = _FakeState(soc, "%")
    coordinator = _make_coordinator(control_mode=BOILER_MODE_AUTO, states=states)
    if split:
        coordinator.battery_sensor_type = BATTERY_SENSOR_TYPE_SPLIT
        coordinator.battery_charge_sensor_id = "sensor.battery_charge"
        coordinator.battery_discharge_sensor_id = "sensor.battery_discharge"
        states["sensor.battery_charge"] = _FakeState(split[0], "W")
        states["sensor.battery_discharge"] = _FakeState(split[1], "W")
    else:
        coordinator.battery_sensor_type = BATTERY_SENSOR_TYPE_NET
        coordinator.battery_power_sensor_id = "sensor.battery_power"
        coordinator.battery_charge_negative = charge_negative
        states["sensor.battery_power"] = _FakeState(battery, "W")
    coordinator.battery_soc_sensor_id = "sensor.battery_soc"
    coordinator.safety_margin_watts = margin
    coordinator.data = {**coordinator.data, "status": {"power": boiler_watts}}
    return coordinator


async def _run_at(coordinator, when):
    with patch(
        "custom_components.powerbaas.devices.boiler_controller.coordinator.dt_util.utcnow",
        return_value=when,
    ):
        await coordinator._async_update()
    # 0W goes out as 0% (see _send_target_watts), so read the mirrored target.
    return coordinator.data["target_watts"]


async def test_battery_at_max_charge_boiler_gets_the_rest() -> None:
    coordinator = _battery_coordinator(grid="-400", battery="800")

    assert await _run_at(coordinator, NOW) == 400
    assert coordinator.data["available_surplus"] == 400


async def test_battery_still_ramping_keeps_its_headroom() -> None:
    coordinator = _battery_coordinator(grid="-700", battery="500")

    # 300 W headroom stays reserved for the battery.
    assert await _run_at(coordinator, NOW) == 400


async def test_battery_stalled_releases_headroom_to_boiler() -> None:
    coordinator = _battery_coordinator(grid="-700", battery="500")

    assert await _run_at(coordinator, NOW) == 400
    assert await _run_at(coordinator, NOW + timedelta(seconds=BATTERY_STALL_SECONDS - 1)) == 400
    assert await _run_at(coordinator, NOW + timedelta(seconds=BATTERY_STALL_SECONDS)) == 700


async def test_rising_battery_restarts_stall_window() -> None:
    coordinator = _battery_coordinator(grid="-700", battery="500")
    await _run_at(coordinator, NOW)

    coordinator.hass._states["sensor.battery_power"] = _FakeState("600", "W")
    coordinator.hass._states["sensor.net_power"] = _FakeState("-600", "W")
    later = NOW + timedelta(seconds=BATTERY_STALL_SECONDS)

    # Still rising - headroom (200 W) remains reserved.
    assert await _run_at(coordinator, later) == 400


async def test_stalled_battery_gets_rechecked() -> None:
    coordinator = _battery_coordinator(grid="-700", battery="500")
    await _run_at(coordinator, NOW)
    stalled = NOW + timedelta(seconds=BATTERY_STALL_SECONDS)
    await _run_at(coordinator, stalled)

    # Boiler now absorbs the export; grid ~0, boiler drawing 700 W.
    coordinator.hass._states["sensor.net_power"] = _FakeState("0", "W")
    coordinator.data = {**coordinator.data, "status": {"power": 700}}
    assert await _run_at(coordinator, stalled + timedelta(seconds=10)) == 700

    recheck = stalled + timedelta(seconds=BATTERY_STALL_RECHECK_SECONDS)
    assert await _run_at(coordinator, recheck) == 400


async def test_stall_clears_when_no_surplus_left() -> None:
    coordinator = _battery_coordinator(grid="-700", battery="500")
    await _run_at(coordinator, NOW)
    stalled = NOW + timedelta(seconds=BATTERY_STALL_SECONDS)
    await _run_at(coordinator, stalled)

    # Cloud: importing, boiler off.
    coordinator.hass._states["sensor.net_power"] = _FakeState("200", "W")
    coordinator.data = {**coordinator.data, "status": {"power": 0}}
    await _run_at(coordinator, stalled + timedelta(seconds=10))

    assert coordinator._battery_stalled_at is None


async def test_battery_full_boiler_gets_everything() -> None:
    coordinator = _battery_coordinator(grid="-1200", battery="0", soc="100")

    assert await _run_at(coordinator, NOW) == 1200


async def test_discharging_battery_never_feeds_boiler() -> None:
    # Boiler drawing 300 W, battery discharging 300 W to cover it, grid 0.
    coordinator = _battery_coordinator(grid="0", battery="-300", soc="80", boiler_watts=300)

    assert await _run_at(coordinator, NOW) == 0


async def test_split_battery_sensors() -> None:
    coordinator = _battery_coordinator(grid="-400", battery="", split=("800", "0"))

    assert await _run_at(coordinator, NOW) == 400


async def test_charge_negative_sign_convention() -> None:
    coordinator = _battery_coordinator(grid="-400", battery="-800", charge_negative=True)

    assert await _run_at(coordinator, NOW) == 400


async def test_without_soc_sensor_headroom_still_reserved() -> None:
    coordinator = _battery_coordinator(grid="-700", battery="500", soc=None)

    assert await _run_at(coordinator, NOW) == 400


async def test_unreadable_battery_falls_back_to_grid_surplus() -> None:
    coordinator = _battery_coordinator(grid="-700", battery="unavailable")

    assert await _run_at(coordinator, NOW) == 700


@pytest.mark.parametrize("battery", [False, True])
async def test_safety_margin_applies_with_and_without_battery(battery: bool) -> None:
    coordinator = _battery_coordinator(grid="-400", battery="800", margin=50)
    if not battery:
        coordinator.battery_sensor_type = "none"

    assert await _run_at(coordinator, NOW) == 350


async def test_available_surplus_cleared_outside_auto_mode() -> None:
    coordinator = _battery_coordinator(grid="-400", battery="800")
    await _run_at(coordinator, NOW)
    coordinator.data = {**coordinator.data, "control_mode": BOILER_MODE_OFF}

    await coordinator._async_update()

    assert coordinator.data["available_surplus"] is None
