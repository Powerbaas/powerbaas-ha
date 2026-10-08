"""Per-port sensor mapping, sub-devices and dynamic port entity creation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerbaas.const import DOMAIN
from custom_components.powerbaas.devices.power_temp import sensor as pt_sensor
from custom_components.powerbaas.devices.power_temp.entity import port_device_info
from custom_components.powerbaas.devices.power_temp.sensor import (
    PowerTempOverallStatusSensor,
    PowerTempPortStatusSensor,
    PowerTempPortTemperatureSensor,
)


def _coordinator(ports: dict, *, online: bool = True, status: str = "ok"):
    listeners: list = []
    return SimpleNamespace(
        data={"sensors": {"status": status}, "system": {}, "config": {}, "ports": ports},
        device_online=online,
        device_name="PowerTemp",
        device_url="http://pt.local",
        known_ports=set(),
        ignored_ports=set(),
        listeners=listeners,
        async_add_listener=lambda cb: listeners.append(cb) or (lambda: None),
    )


def _port_entity(cls, coordinator, port: int):
    entity = object.__new__(cls)
    entity.coordinator = coordinator
    entity._port = port
    return entity


def test_port_sub_device_is_named_after_sensor_and_linked_to_hub() -> None:
    coordinator = _coordinator({3: {"port": 3, "name": "Groep 3"}, 4: {"port": 4, "name": ""}})
    entry = SimpleNamespace(entry_id="pt_entry")

    info = port_device_info(coordinator, entry, 3)
    assert info["name"] == "Groep 3"
    assert info["identifiers"] == {(DOMAIN, "pt_entry_port_3")}
    assert info["via_device"] == (DOMAIN, "pt_entry")
    assert port_device_info(coordinator, entry, 4)["name"] == "Temp 4"


def test_port_temperature_entity() -> None:
    coordinator = _coordinator(
        {3: {"port": 3, "name": "Groep 3", "celsius": 31.2, "status": "warning", "type": "ds18b20"}}
    )
    entity = _port_entity(PowerTempPortTemperatureSensor, coordinator, 3)

    assert entity._attr_name == "Temperature"
    assert entity.available is True
    assert entity.native_value == 31.2
    assert entity.extra_state_attributes["status"] == "warning"


def test_port_temperature_unavailable_without_reading() -> None:
    coordinator = _coordinator({5: {"port": 5, "celsius": None, "status": "missing"}})

    assert _port_entity(PowerTempPortTemperatureSensor, coordinator, 5).available is False


def test_port_status_stays_available_when_sensor_missing() -> None:
    coordinator = _coordinator({5: {"port": 5, "celsius": None, "status": "missing"}})
    entity = _port_entity(PowerTempPortStatusSensor, coordinator, 5)

    assert entity.available is True
    assert entity.native_value == "missing"


def test_port_entities_unavailable_when_device_offline() -> None:
    coordinator = _coordinator({1: {"port": 1, "celsius": 20.0, "status": "ok"}}, online=False)

    assert _port_entity(PowerTempPortTemperatureSensor, coordinator, 1).available is False
    assert _port_entity(PowerTempPortStatusSensor, coordinator, 1).available is False


def test_overall_status_rejects_unknown_values() -> None:
    entity = object.__new__(PowerTempOverallStatusSensor)
    entity.coordinator = _coordinator({}, status="bogus")

    assert entity.native_value is None
    assert entity.available is False


async def test_new_ports_get_entities_on_coordinator_update(hass) -> None:
    coordinator = _coordinator({1: {"port": 1, "celsius": 20.0, "status": "ok"}})
    entry = MagicMock()
    entry.entry_id = "pt_entry"
    hass.data[DOMAIN] = {"pt_entry": {"coordinator": coordinator}}
    added: list = []

    await pt_sensor.async_setup_entry(hass, entry, lambda entities: added.extend(entities))
    port_ids = lambda: sorted(e.unique_id for e in added if "_port_" in e.unique_id)  # noqa: E731

    assert port_ids() == ["pt_entry_port_1_status", "pt_entry_port_1_temperature"]

    coordinator.data["ports"][7] = {"port": 7, "celsius": 25.0, "status": "ok"}
    for listener in coordinator.listeners:
        listener()
    # Re-firing with no new ports must not duplicate entities.
    for listener in coordinator.listeners:
        listener()

    assert port_ids() == [
        "pt_entry_port_1_status",
        "pt_entry_port_1_temperature",
        "pt_entry_port_7_status",
        "pt_entry_port_7_temperature",
    ]


async def test_ignored_port_gets_no_entities(hass) -> None:
    coordinator = _coordinator({1: {"port": 1}, 2: {"port": 2}})
    coordinator.ignored_ports.add(2)
    entry = MagicMock()
    entry.entry_id = "pt_entry"
    hass.data[DOMAIN] = {"pt_entry": {"coordinator": coordinator}}
    added: list = []

    await pt_sensor.async_setup_entry(hass, entry, lambda entities: added.extend(entities))

    assert not any("_port_2_" in e.unique_id for e in added)


async def test_rename_on_device_updates_sub_device_name(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="pt_entry")
    entry.add_to_hass(hass)
    coordinator = _coordinator({1: {"port": 1, "name": "Groep 1", "celsius": 20.0}})
    hass.data[DOMAIN] = {"pt_entry": {"coordinator": coordinator}}
    registry = dr.async_get(hass)
    registry.async_get_or_create(config_entry_id="pt_entry", identifiers={(DOMAIN, "pt_entry")})
    device = registry.async_get_or_create(
        config_entry_id="pt_entry", **port_device_info(coordinator, entry, 1)
    )

    await pt_sensor.async_setup_entry(hass, entry, lambda _entities: None)
    coordinator.data["ports"][1]["name"] = "Wasmachine"
    for listener in coordinator.listeners:
        listener()

    assert registry.async_get(device.id).name == "Wasmachine"
