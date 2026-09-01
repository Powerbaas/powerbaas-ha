"""Color-blind switch command mapping against a fake coordinator/client."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.powerbaas.devices.rgb.switch import RgbColorBlindSwitch


def _switch(*, rgb: dict, system: dict | None = None, online: bool = True) -> RgbColorBlindSwitch:
    client = SimpleNamespace(async_set_rgb=AsyncMock(return_value=True))
    coordinator = SimpleNamespace(
        data={"rgb": rgb, "system": system or {"mode": "Standalone"}},
        device_online=online,
        device_name="Powerbaas RGB",
        device_url="http://rgb.local",
        client=client,
        async_request_refresh=AsyncMock(),
    )
    coordinator.async_set_updated_data = MagicMock(
        side_effect=lambda data: setattr(coordinator, "data", data)
    )
    entry = MagicMock()
    entry.entry_id = "rgb_entry"
    switch = object.__new__(RgbColorBlindSwitch)
    switch.coordinator = coordinator
    switch._entry = entry
    switch._attr_unique_id = "rgb_entry_color_blind"
    switch._attr_device_info = {}
    switch._command_seq = 0
    return switch


async def test_turn_on_sends_color_blind_flag() -> None:
    switch = _switch(rgb={"colorBlind": False})

    await RgbColorBlindSwitch.async_turn_on(switch)

    switch.coordinator.client.async_set_rgb.assert_awaited_once_with(colorBlind=1)


async def test_turn_off_sends_color_blind_flag() -> None:
    switch = _switch(rgb={"colorBlind": True})

    await RgbColorBlindSwitch.async_turn_off(switch)

    switch.coordinator.client.async_set_rgb.assert_awaited_once_with(colorBlind=0)


# Regression tests for the toggle-flicker bug (see test_rgb_light.py): a
# refresh right after the command can race the firmware and read back stale
# state. The fix updates coordinator.data optimistically instead.


async def test_turn_on_reflects_immediately_without_refetch() -> None:
    switch = _switch(rgb={"colorBlind": False})

    await RgbColorBlindSwitch.async_turn_on(switch)

    assert RgbColorBlindSwitch.is_on.fget(switch) is True
    switch.coordinator.async_request_refresh.assert_not_awaited()
    switch.coordinator.async_set_updated_data.assert_called_once()


async def test_turn_off_reflects_immediately_without_refetch() -> None:
    switch = _switch(rgb={"colorBlind": True})

    await RgbColorBlindSwitch.async_turn_off(switch)

    assert RgbColorBlindSwitch.is_on.fget(switch) is False
    switch.coordinator.async_request_refresh.assert_not_awaited()


def test_unavailable_when_offline() -> None:
    switch = _switch(rgb={"colorBlind": True}, online=False)

    assert RgbColorBlindSwitch.available.fget(switch) is False
