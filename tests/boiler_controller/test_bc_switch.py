"""SSR switch command mapping against a fake coordinator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.powerbaas.devices.boiler_controller.switch import BoilerControllerSsrSwitch


def _ssr_switch(*, status: dict | None, online: bool = True) -> BoilerControllerSsrSwitch:
    coordinator = SimpleNamespace(
        data={"status": status},
        device_online=online,
        async_set_ssr=AsyncMock(),
    )
    entry = MagicMock()
    entry.entry_id = "bc_entry"
    switch = object.__new__(BoilerControllerSsrSwitch)
    switch.coordinator = coordinator
    switch.config_entry = entry
    return switch


def test_ssr_is_on_reads_status() -> None:
    switch = _ssr_switch(status={"ssr": {"on": True}})

    assert BoilerControllerSsrSwitch.is_on.fget(switch) is True
    assert BoilerControllerSsrSwitch.available.fget(switch) is True


def test_ssr_unavailable_when_field_missing() -> None:
    switch = _ssr_switch(status={})

    assert BoilerControllerSsrSwitch.available.fget(switch) is False


def test_ssr_unavailable_when_status_missing() -> None:
    switch = _ssr_switch(status=None)

    assert BoilerControllerSsrSwitch.available.fget(switch) is False


def test_ssr_unavailable_when_offline() -> None:
    switch = _ssr_switch(status={"ssr": {"on": True}}, online=False)

    assert BoilerControllerSsrSwitch.available.fget(switch) is False


async def test_ssr_turn_on_delegates() -> None:
    switch = _ssr_switch(status={"ssr": {"on": False}})

    await BoilerControllerSsrSwitch.async_turn_on(switch)

    switch.coordinator.async_set_ssr.assert_awaited_once_with(True)


async def test_ssr_turn_off_delegates() -> None:
    switch = _ssr_switch(status={"ssr": {"on": True}})

    await BoilerControllerSsrSwitch.async_turn_off(switch)

    switch.coordinator.async_set_ssr.assert_awaited_once_with(False)
