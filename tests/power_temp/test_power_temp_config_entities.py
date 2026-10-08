"""Hub config entities: thresholds (number), delta limits (switch), ambient sensor (select)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.powerbaas.devices.power_temp.client import PowerTempCommandError
from custom_components.powerbaas.devices.power_temp.number import PowerTempConfigNumber
from custom_components.powerbaas.devices.power_temp.select import NO_AMBIENT, PowerTempAmbientSelect
from custom_components.powerbaas.devices.power_temp.switch import PowerTempDeltaSwitch


def _coordinator(*, online: bool = True):
    return SimpleNamespace(
        device_online=online,
        device_name="Powerbaas PowerTemp",
        data={
            "config": {
                "thresholds": {"warnC": 45, "alarmC": 60, "hysteresisC": 2},
                "delta": {"enabled": True, "warnC": 10, "alarmC": 20},
                "sensors": [
                    {"port": 1, "name": "Groep 1", "ambient": False},
                    {"port": 16, "name": "Ambient", "ambient": True},
                ],
            },
            "ports": {
                1: {"port": 1, "name": "Groep 1"},
                5: {"port": 5, "name": ""},
                16: {"port": 16, "name": "Ambient"},
            },
        },
        async_update_config=AsyncMock(),
        async_set_ambient_port=AsyncMock(),
    )


def _entity(cls, coordinator, path):
    entity = object.__new__(cls)
    entity.coordinator = coordinator
    entity._path = path
    return entity


async def test_threshold_number_reads_and_writes_nested_value() -> None:
    coordinator = _coordinator()
    number = _entity(PowerTempConfigNumber, coordinator, ["thresholds", "warnC"])

    assert number.native_value == 45
    await number.async_set_native_value(50)

    coordinator.async_update_config.assert_awaited_once_with({"thresholds": {"warnC": 50}})


async def test_rejected_value_raises_home_assistant_error() -> None:
    coordinator = _coordinator()
    coordinator.async_update_config.side_effect = PowerTempCommandError("invalid_thresholds")
    number = _entity(PowerTempConfigNumber, coordinator, ["thresholds", "alarmC"])

    with pytest.raises(HomeAssistantError, match="invalid_thresholds"):
        await number.async_set_native_value(10)


def test_config_entities_unavailable_when_offline() -> None:
    number = _entity(PowerTempConfigNumber, _coordinator(online=False), ["thresholds", "warnC"])

    assert number.available is False


async def test_delta_switch() -> None:
    coordinator = _coordinator()
    switch = _entity(PowerTempDeltaSwitch, coordinator, ["delta", "enabled"])

    assert switch.is_on is True
    await switch.async_turn_off()

    coordinator.async_update_config.assert_awaited_once_with({"delta": {"enabled": False}})


async def test_ambient_select_options_and_selection() -> None:
    coordinator = _coordinator()
    select = _entity(PowerTempAmbientSelect, coordinator, ["sensors"])

    assert select.options == [NO_AMBIENT, "Groep 1 (port 1)", "Port 5", "Ambient (port 16)"]
    assert select.current_option == "Ambient (port 16)"

    await select.async_select_option("Port 5")
    coordinator.async_set_ambient_port.assert_awaited_once_with(5)


async def test_ambient_select_clear() -> None:
    coordinator = _coordinator()
    select = _entity(PowerTempAmbientSelect, coordinator, ["sensors"])

    await select.async_select_option(NO_AMBIENT)

    coordinator.async_set_ambient_port.assert_awaited_once_with(None)
