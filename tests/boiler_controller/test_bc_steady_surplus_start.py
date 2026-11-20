"""A start held back for confirmation must also start on a steady surplus.

Seen against the Powerbaas devices simulator: a battery charging at its max
and a steady 2297 W export. With a battery the boiler only starts once a
second grid reading agrees (see _async_update), but Auto mode only reacted
to a changed sensor value - the P1 kept reporting exactly the same value,
so that second reading never came and the boiler stayed off.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.util import dt as dt_util

from tests.boiler_controller.test_bc_battery_priority import _battery_coordinator
from tests.boiler_controller.test_bc_coordinator import _FakeState

NOW = dt_util.utcnow()
UTCNOW = "custom_components.powerbaas.devices.boiler_controller.coordinator.dt_util.utcnow"


def _changed(old: str, new: str):
    return SimpleNamespace(
        data={"entity_id": "sensor.net_power", "old_state": _FakeState(old, "W"), "new_state": _FakeState(new, "W")}
    )


def _reported(value: str):
    return SimpleNamespace(data={"entity_id": "sensor.net_power", "new_state": _FakeState(value, "W")})


async def _at(seconds: float, call):
    with patch(UTCNOW, return_value=NOW + timedelta(seconds=seconds)):
        await call


async def test_steady_surplus_confirms_the_start() -> None:
    # Battery at its 800 W max: no headroom left, the export is for the boiler.
    coordinator = _battery_coordinator(grid="-2297", battery="800", soc="60")

    await _at(0, coordinator._async_power_sensor_changed(_changed("0", "-2297")))
    assert coordinator._auto_start_pending
    assert coordinator.data["target_watts"] == 0

    # The P1 reports the same export again: that's the confirming reading.
    await _at(12, coordinator._async_power_sensor_reported(_reported("-2297")))
    assert coordinator.data["target_watts"] == 2000  # the max heating power


async def test_same_value_within_the_rate_limit_waits() -> None:
    coordinator = _battery_coordinator(grid="-2297", battery="800", soc="60")
    await _at(0, coordinator._async_power_sensor_changed(_changed("0", "-2297")))

    await _at(3, coordinator._async_power_sensor_reported(_reported("-2297")))
    assert coordinator._auto_start_pending
    assert coordinator.data["target_watts"] == 0


async def test_same_value_without_a_pending_start_does_nothing() -> None:
    coordinator = _battery_coordinator(grid="-2297", battery="800", soc="60")

    with patch.object(coordinator, "_async_update") as update:
        await _at(12, coordinator._async_power_sensor_reported(_reported("-2297")))
    update.assert_not_called()
