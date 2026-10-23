"""Battery switching between charge and discharge must not hand its surplus to the boiler.

Replays a Zendure (Zendure Manager, charging reported negative, max charge
2400 W) from production logs: switching between charging and discharging it
always passes through idle, for 8 s up to several minutes, while the P1
exports. The old 30 s stall window, measured from a moment of grid import,
released the whole export to the boiler before the battery started charging.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from custom_components.powerbaas.devices.boiler_controller.const import (
    BATTERY_STALL_SECONDS,
)

from tests.boiler_controller.test_bc_battery_priority import (
    NOW,
    _battery_coordinator,
    _run_at,
)
from tests.boiler_controller.test_bc_coordinator import _FakeState


def _zendure_coordinator(soc: str | None):
    coordinator = _battery_coordinator(grid="385", battery="0", soc=soc, charge_negative=True)
    coordinator.battery_max_charge_watts = 2400.0
    coordinator.data = {**coordinator.data, "max_heating_watts": 2500}
    return coordinator


async def _step(
    coordinator, seconds: float, *, grid: str, battery: str, confirm_start: bool = True
) -> int:
    coordinator.hass._states["sensor.net_power"] = _FakeState(grid, "W")
    coordinator.hass._states["sensor.battery_power"] = _FakeState(battery, "W")
    return await _run_at(
        coordinator, NOW + timedelta(seconds=seconds), confirm_start=confirm_start
    )


@pytest.mark.parametrize("soc", ["14", None])
async def test_battery_switching_over_keeps_its_headroom(soc: str | None) -> None:
    """2026-10-19 10:52: boiler got 1757 W while the battery was about to charge."""
    coordinator = _zendure_coordinator(soc)

    assert await _step(coordinator, 0, grid="385", battery="0") == 0
    # Battery still discharging while export appears.
    assert await _step(coordinator, 12, grid="-626", battery="873") == 0
    assert await _step(coordinator, 24, grid="-1895", battery="0") == 0
    # Old behavior: stall released here, boiler got the full 1757 W.
    assert await _step(coordinator, 36, grid="-1757", battery="0") == 0

    # Battery idle on export while Zendure Manager catches up (64 s in the logs).
    for seconds in range(48, 24 + 75, 12):
        assert await _step(coordinator, seconds, grid="-1800", battery="0") == 0
    assert coordinator._battery_stalled_at is None


@pytest.mark.parametrize("soc", ["14", None])
async def test_periodic_import_does_not_flap_boiler(soc: str | None) -> None:
    """2026-10-19 13:26-13:50: boiler toggled Running/Idle every minute."""
    coordinator = _zendure_coordinator(soc)

    targets = []
    for minute in range(10):
        base = minute * 60
        # ~16 s of import each minute, ~600 W export the rest, battery idle.
        targets.append(await _step(coordinator, base + 13, grid="1150", battery="0"))
        targets.append(await _step(coordinator, base + 25, grid="969", battery="0"))
        for offset in (37, 49, 60.9):
            targets.append(await _step(coordinator, base + offset, grid="-600", battery="0"))

    assert set(targets) == {0}


async def test_with_soc_battery_idle_on_export_never_releases() -> None:
    """13:25-13:28: idle for minutes on export - with a SOC the battery keeps priority."""
    coordinator = _zendure_coordinator("20")

    for seconds in range(0, 10 * 60, 12):
        assert await _step(coordinator, seconds, grid="-1800", battery="0") == 0


async def test_with_soc_battery_full_boiler_gets_surplus() -> None:
    coordinator = _zendure_coordinator("99")

    assert await _step(coordinator, 0, grid="-1800", battery="0") == 1800


async def test_without_soc_really_stalled_battery_still_releases() -> None:
    coordinator = _zendure_coordinator(None)

    await _step(coordinator, 0, grid="-1800", battery="0")
    assert await _step(coordinator, BATTERY_STALL_SECONDS - 1, grid="-1800", battery="0") == 0
    assert await _step(coordinator, BATTERY_STALL_SECONDS, grid="-1800", battery="0") == 1800
