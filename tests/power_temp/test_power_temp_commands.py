"""Coordinator config commands (read-modify-write of the sensor list) and sub-device removal."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.powerbaas.const import DOMAIN
from custom_components.powerbaas.devices.power_temp import (
    PowerTempCoordinator,
    async_remove_config_entry_device,
)
from custom_components.powerbaas.devices.power_temp.client import PowerTempCommandError

DEVICE_CONFIG = {
    "thresholds": {"warnC": 45, "alarmC": 60, "hysteresisC": 2},
    "sensors": [
        {"port": 1, "name": "Groep 1", "offsetC": 0.5, "enabled": True, "ambient": False},
        {"port": 16, "name": "Ambient", "offsetC": 0, "enabled": True, "ambient": True},
    ],
}


def _coordinator(*, ports: dict | None = None) -> PowerTempCoordinator:
    coordinator = object.__new__(PowerTempCoordinator)
    coordinator.client = SimpleNamespace(
        async_get_config=AsyncMock(return_value=copy.deepcopy(DEVICE_CONFIG)),
        async_update_config=AsyncMock(return_value={}),
    )
    coordinator.async_refresh = AsyncMock()
    coordinator.device_name = "PowerTemp"
    coordinator.known_ports = set(ports or {})
    coordinator.ignored_ports = set()
    coordinator.data = {"config": copy.deepcopy(DEVICE_CONFIG), "ports": ports or {}}
    return coordinator


def _posted_sensors(coordinator) -> list[dict]:
    body = coordinator.client.async_update_config.await_args.args[0]
    assert set(body) == {"sensors"}
    return body["sensors"]


async def test_update_config_posts_and_refreshes() -> None:
    coordinator = _coordinator()

    await coordinator.async_update_config({"thresholds": {"warnC": 50}})

    coordinator.client.async_update_config.assert_awaited_once_with({"thresholds": {"warnC": 50}})
    coordinator.async_refresh.assert_awaited_once()


async def test_save_sensor_adopts_new_port_and_keeps_others_intact() -> None:
    coordinator = _coordinator()

    await coordinator.async_save_sensor(5, name="Groep 5", offset_c=-0.3, enabled=True)

    assert _posted_sensors(coordinator) == [
        *DEVICE_CONFIG["sensors"],
        {"port": 5, "name": "Groep 5", "offsetC": -0.3, "enabled": True, "ambient": False},
    ]


async def test_save_sensor_only_changes_given_fields() -> None:
    coordinator = _coordinator()

    await coordinator.async_save_sensor(1, name="Wasmachine")

    assert _posted_sensors(coordinator)[0] == {
        "port": 1, "name": "Wasmachine", "offsetC": 0.5, "enabled": True, "ambient": False,
    }


async def test_sensor_list_is_read_fresh_from_device() -> None:
    # A sensor added in the web UI since the last poll must not be dropped.
    coordinator = _coordinator()
    fresh = copy.deepcopy(DEVICE_CONFIG)
    fresh["sensors"].append({"port": 9, "name": "Web UI", "offsetC": 0, "enabled": True, "ambient": False})
    coordinator.client.async_get_config.return_value = fresh

    await coordinator.async_save_sensor(1, name="Wasmachine")

    assert [s["port"] for s in _posted_sensors(coordinator)] == [1, 16, 9]


async def test_remove_sensor() -> None:
    coordinator = _coordinator()

    await coordinator.async_remove_sensor(1)

    assert [s["port"] for s in _posted_sensors(coordinator)] == [16]


async def test_set_ambient_moves_flag_and_adopts_port() -> None:
    coordinator = _coordinator()

    await coordinator.async_set_ambient_port(7)

    sensors = {s["port"]: s for s in _posted_sensors(coordinator)}
    assert [p for p, s in sensors.items() if s["ambient"]] == [7]
    assert sensors[16]["ambient"] is False


async def test_clear_ambient() -> None:
    coordinator = _coordinator()

    await coordinator.async_set_ambient_port(None)

    assert not any(s["ambient"] for s in _posted_sensors(coordinator))


async def test_sensor_change_fails_when_config_unreadable() -> None:
    coordinator = _coordinator()
    coordinator.client.async_get_config.return_value = None

    with pytest.raises(PowerTempCommandError):
        await coordinator.async_remove_sensor(1)
    coordinator.client.async_update_config.assert_not_awaited()


def _remove_device(coordinator, identifier: str):
    hass = SimpleNamespace(data={DOMAIN: {"pt_entry": {"coordinator": coordinator}}})
    entry = SimpleNamespace(entry_id="pt_entry")
    device = SimpleNamespace(identifiers={(DOMAIN, identifier)})
    return async_remove_config_entry_device(hass, entry, device)


async def test_hub_device_cannot_be_removed() -> None:
    assert await _remove_device(_coordinator(), "pt_entry") is False


async def test_port_with_sensor_still_connected_cannot_be_removed() -> None:
    coordinator = _coordinator(ports={1: {"port": 1, "present": True, "configured": True}})

    assert await _remove_device(coordinator, "pt_entry_port_1") is False
    coordinator.client.async_update_config.assert_not_awaited()


async def test_removing_unplugged_port_drops_it_from_device_config() -> None:
    coordinator = _coordinator(ports={1: {"port": 1, "present": False, "configured": True}})

    assert await _remove_device(coordinator, "pt_entry_port_1") is True
    assert [s["port"] for s in _posted_sensors(coordinator)] == [16]
    # So entities are recreated if a sensor is plugged into this port again,
    # but not while the firmware still lists it as a recently seen port.
    assert 1 not in coordinator.known_ports
    assert 1 in coordinator.ignored_ports


async def test_removing_unconfigured_missing_port_only_ignores_it() -> None:
    coordinator = _coordinator(ports={5: {"port": 5, "present": False, "configured": False}})

    assert await _remove_device(coordinator, "pt_entry_port_5") is True
    coordinator.client.async_update_config.assert_not_awaited()
    assert 5 in coordinator.ignored_ports


async def test_removing_plugged_in_sensor_from_config_does_not_ignore_it() -> None:
    # It turns back into a new sensor, which should raise the adopt issue again.
    coordinator = _coordinator(ports={1: {"port": 1, "present": True, "configured": True}})

    await coordinator.async_remove_sensor(1)

    assert coordinator.ignored_ports == set()


async def test_removing_port_fails_when_device_rejects_it() -> None:
    coordinator = _coordinator(ports={1: {"port": 1, "present": False, "configured": True}})
    coordinator.client.async_update_config.side_effect = PowerTempCommandError("save_failed")

    assert await _remove_device(coordinator, "pt_entry_port_1") is False
    assert 1 in coordinator.known_ports
    assert 1 not in coordinator.ignored_ports
