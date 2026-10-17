"""A 0W target must be sent as 0%, not as a 0W wattage target.

The firmware's wattage control treats "measured 0W, target 0W" as "not too
high" and probes up to 1%. With the boiler's thermostat satisfied it keeps
measuring 0W and stays at 1% until the next command, so Status flapped
between Idle and Running while Target Power stayed at 0W. POST
/api/heat/percentage disables wattage control on the device, so 0% sticks.
"""

from __future__ import annotations

from custom_components.powerbaas.devices.boiler_controller.const import (
    BOILER_MODE_AUTO,
    BOILER_MODE_MANUAL,
)

from tests.boiler_controller.test_bc_coordinator import _FakeState, _make_coordinator


async def test_auto_mode_zero_watts_sends_zero_percent() -> None:
    coordinator = _make_coordinator(
        control_mode=BOILER_MODE_AUTO,
        states={"sensor.net_power": _FakeState("500", "W")},  # importing
    )
    coordinator.data = {**coordinator.data, "status": {"power": 0}}

    await coordinator._async_update()

    assert coordinator.device_client.target_watts_calls == []
    assert coordinator.device_client.heating_percentage_calls == [0]
    assert coordinator.data["target_watts"] == 0


async def test_auto_mode_zero_watts_resends_even_if_last_poll_saw_zero_percent() -> None:
    """The device can drift to 1% between polls, so never dedupe the 0%."""
    coordinator = _make_coordinator(
        control_mode=BOILER_MODE_AUTO,
        states={"sensor.net_power": _FakeState("500", "W")},
    )
    coordinator._current_dimmer_percentage = 0

    await coordinator._async_update()
    await coordinator._async_update()

    assert coordinator.device_client.heating_percentage_calls == [0, 0]


async def test_manual_mode_zero_watts_sends_zero_percent() -> None:
    coordinator = _make_coordinator(control_mode=BOILER_MODE_MANUAL, target_watts=0)

    await coordinator._async_update()

    assert coordinator.device_client.target_watts_calls == []
    assert coordinator.device_client.heating_percentage_calls == [0]


async def test_nonzero_watts_still_uses_wattage_control() -> None:
    coordinator = _make_coordinator(control_mode=BOILER_MODE_MANUAL, target_watts=750)

    await coordinator._async_update()

    assert coordinator.device_client.target_watts_calls == [750]
    assert coordinator.device_client.heating_percentage_calls == []
