"""End-to-end: a real config entry setup through Home Assistant, with a fake device."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerbaas import async_remove_config_entry_device
from custom_components.powerbaas.const import CONF_DEVICE_TYPE, DEVICE_TYPE_POWER_TEMP, DOMAIN
from custom_components.powerbaas.devices.power_temp import new_sensor_issue_id

SENSORS = {
    "status": "ok",
    "deviceName": "Meterkast",
    "ambientC": None,
    "temperatures": [
        {"port": 1, "type": "ds18b20", "name": "Groep 1", "configured": True, "enabled": True,
         "ambient": False, "present": True, "celsius": 28.3, "deltaC": None, "status": "ok", "ageS": 2},
        {"port": 2, "type": "ntc", "name": "Groep 2", "configured": True, "enabled": True,
         "ambient": False, "present": False, "celsius": None, "deltaC": None, "status": "missing", "ageS": None},
        {"port": 5, "type": "ntc", "name": "", "configured": False, "enabled": True,
         "ambient": False, "present": True, "celsius": 30.1, "deltaC": None, "status": "ok", "ageS": 1},
    ],
}
CONFIG = {
    "deviceName": "Meterkast",
    "pollIntervalS": 10,
    "thresholds": {"warnC": 45, "alarmC": 60, "hysteresisC": 2},
    "delta": {"enabled": True, "warnC": 10, "alarmC": 20},
    "sensors": [
        {"port": 1, "name": "Groep 1", "offsetC": 0, "enabled": True, "ambient": False},
        {"port": 2, "name": "Groep 2", "offsetC": 0, "enabled": True, "ambient": False},
    ],
}
SYSTEM = {"firmwareVersion": 3, "hostname": "pb-pt-aabbccddeeff", "ip": "192.168.1.20"}


class _FakeResponse:
    def __init__(self, json_data: Any, status: int = 200) -> None:
        self.status = status
        self._json_data = json_data

    async def json(self, content_type=None):  # noqa: ANN001
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return False


class _FakeDevice:
    """Answers by path, like the real firmware, and records config POSTs."""

    def __init__(self) -> None:
        self.responses = {
            "/api/sensors": copy.deepcopy(SENSORS),
            "/api/system": copy.deepcopy(SYSTEM),
            "/api/config": copy.deepcopy(CONFIG),
        }
        self.posted: list[dict] = []

    def get(self, url: str, timeout=None, params=None):  # noqa: ANN001
        return _FakeResponse(self.responses[url.removeprefix("http://pt.local")])

    def post(self, url: str, json=None, timeout=None):  # noqa: ANN001
        self.posted.append(json)
        return _FakeResponse(self.responses["/api/config"])


@pytest.fixture
async def setup(hass, enable_custom_integrations, monkeypatch: pytest.MonkeyPatch):
    device = _FakeDevice()
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.power_temp.client.async_get_clientsession",
        lambda _hass: device,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_POWER_TEMP,
            "device_url": "http://pt.local",
            "device_id": "pb-pt-aabbccddeeff",
        },
        title="Meterkast",
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry, device
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass, domain: str, unique_suffix: str, entry) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{unique_suffix}")


async def test_port_sub_devices_hang_under_hub(hass, setup) -> None:
    entry, _ = setup
    registry = dr.async_get(hass)
    hub = registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    port1 = registry.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_port_1")})
    port5 = registry.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_port_5")})

    assert entry.state is ConfigEntryState.LOADED
    assert hub.name == "PowerTemp Manager"
    assert port1.name == "Groep 1"
    assert port1.via_device_id == hub.id
    assert port5.name == "Temp 5"

    temperature = hass.states.get(_entity_id(hass, "sensor", "port_1_temperature", entry))
    assert temperature.state == "28.3"
    assert temperature.attributes["friendly_name"] == "Groep 1 Temperature"


async def test_config_entities_and_new_sensor_issue(hass, setup) -> None:
    entry, device = setup

    assert hass.states.get(_entity_id(hass, "number", "warn_c", entry)).state == "45"
    assert hass.states.get(_entity_id(hass, "switch", "delta_enabled", entry)).state == "on"
    assert hass.states.get(_entity_id(hass, "select", "ambient_sensor", entry)).state == "None"
    assert issue_registry.async_get(hass).async_get_issue(
        DOMAIN, new_sensor_issue_id(entry.entry_id, 5)
    ) is not None

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": _entity_id(hass, "number", "warn_c", entry), "value": 50},
        blocking=True,
    )
    assert device.posted[-1] == {"thresholds": {"warnC": 50.0}}


async def test_unplugged_port_device_can_be_removed(hass, setup) -> None:
    entry, device = setup
    registry = dr.async_get(hass)
    port1 = registry.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_port_1")})
    port2 = registry.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_port_2")})

    assert await async_remove_config_entry_device(hass, entry, port1) is False
    assert await async_remove_config_entry_device(hass, entry, port2) is True
    assert [s["port"] for s in device.posted[-1]["sensors"]] == [1]
