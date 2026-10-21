"""A lagging battery sensor must not start the boiler for one tick.

Replays a Zendure (Zendure Manager, charging reported negative, max charge
2400 W, SOC 15%) from production logs, 2026-10-21 10:58: the battery stopped
charging 1601 W, the P1 (updating every 4 s) flipped to 1072 W export right
away, but the battery sensor (every 8 s) still reported charging 1601 W. That
tick counted the same watts twice - as export and as charge already taken -
leaving 271 W "available", and the boiler ran for ~10 s.
"""

from __future__ import annotations

from custom_components.powerbaas.devices.boiler_controller.const import (
    BATTERY_SENSOR_TYPE_NONE,
)

from tests.boiler_controller.test_bc_battery_transition_delay import (
    _step as _confirmed_step,
    _zendure_coordinator,
)


async def _step(coordinator, seconds: float, *, grid: str, battery: str) -> int:
    return await _confirmed_step(
        coordinator, seconds, grid=grid, battery=battery, confirm_start=False
    )


async def test_stale_battery_charge_does_not_start_boiler() -> None:
    coordinator = _zendure_coordinator("15")

    assert await _step(coordinator, 0, grid="586", battery="-1601") == 0
    # P1 already shows the export, the battery sensor still the old charge.
    assert await _step(coordinator, 12, grid="-1072", battery="-1601") == 0
    assert await _step(coordinator, 24, grid="-1083", battery="0") == 0


async def test_without_battery_boiler_starts_right_away() -> None:
    coordinator = _zendure_coordinator("99")
    coordinator.battery_sensor_type = BATTERY_SENSOR_TYPE_NONE

    assert await _step(coordinator, 0, grid="-1800", battery="0") == 1800


async def test_lasting_surplus_starts_boiler_on_second_tick() -> None:
    coordinator = _zendure_coordinator("99")

    assert await _step(coordinator, 0, grid="-1800", battery="0") == 0
    assert await _step(coordinator, 12, grid="-1800", battery="0") == 1800


async def test_running_boiler_follows_surplus_without_delay() -> None:
    coordinator = _zendure_coordinator("99")

    await _step(coordinator, 0, grid="-1800", battery="0")
    assert await _step(coordinator, 12, grid="-1800", battery="0") == 1800
    coordinator.data["status"] = {"power": 1800}
    assert await _step(coordinator, 24, grid="300", battery="0") == 1500
    assert await _step(coordinator, 36, grid="2000", battery="0") == 0
    coordinator.data["status"] = {"power": 0}
    # Stopped: starting again needs two ticks once more.
    assert await _step(coordinator, 48, grid="-1800", battery="0") == 0
    assert await _step(coordinator, 60, grid="-1800", battery="0") == 1800
