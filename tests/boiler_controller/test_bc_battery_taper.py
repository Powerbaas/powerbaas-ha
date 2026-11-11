"""Near-full battery taper: only a small charge headroom stays reserved.

2026-10-20 production (Zendure, max charge 2400 W): at 98% the battery
swung between 200 and 400 W (topping off / calibrating) while 1.2 kW went to
the grid. Below "full" the whole 2400 W headroom stayed reserved, so the
boiler got nothing. With "slow charging from" set, only the configured taper
watts stay reserved for the battery between that level and full.
"""

from __future__ import annotations

import pytest

from tests.boiler_controller.test_bc_battery_transition_delay import (
    _step,
    _zendure_coordinator,
)


def _taper_coordinator(soc: str, *, taper_soc: float | None = 95, taper_watts: float | None = 500):
    coordinator = _zendure_coordinator(soc)
    coordinator.battery_full_soc = 100.0
    coordinator.battery_taper_soc = taper_soc
    coordinator.battery_taper_watts = taper_watts
    return coordinator


async def test_topping_off_battery_leaves_rest_to_boiler() -> None:
    coordinator = _taper_coordinator("98")

    # Battery takes 300 W of max 500 W -> 200 W stays reserved for it.
    assert await _step(coordinator, 0, grid="-1200", battery="-300") == 1000
    # Swings up to 400 W: only 100 W stays reserved.
    assert await _step(coordinator, 10, grid="-1100", battery="-400") == 1000


@pytest.mark.parametrize(("battery", "expected"), [("-200", 900), ("-400", 1100), ("-600", 1200)])
async def test_taper_reserve_includes_what_battery_already_takes(battery: str, expected: int) -> None:
    coordinator = _taper_coordinator("96")

    assert await _step(coordinator, 0, grid="-1200", battery=battery) == expected


async def test_below_taper_soc_whole_headroom_stays_reserved() -> None:
    coordinator = _taper_coordinator("94")

    assert await _step(coordinator, 0, grid="-1200", battery="-300") == 0


async def test_full_battery_boiler_gets_everything() -> None:
    coordinator = _taper_coordinator("100")

    assert await _step(coordinator, 0, grid="-1200", battery="-300") == 1200


async def test_taper_not_configured_keeps_old_behavior() -> None:
    coordinator = _taper_coordinator("98", taper_soc=None, taper_watts=None)

    assert await _step(coordinator, 0, grid="-1200", battery="-300") == 0


async def test_idle_battery_in_taper_zone_keeps_taper_reserve() -> None:
    coordinator = _taper_coordinator("97")

    assert await _step(coordinator, 0, grid="-1200", battery="0") == 700
