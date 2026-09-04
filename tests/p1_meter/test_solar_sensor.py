"""Solar sensors live on their own "Solar" device (connected via the P1
meter device) rather than the main P1 device - see SOLAR_SENSORS in
p1_meter/const.py and its device_info override in sensor.py.

Goes through a real `hass.config_entries.async_setup()` (like
test_battery_sensor.py's lifecycle tests) because what's under test is the
device registry side effect of a custom `device_info`, which only happens
through the real entity platform machinery.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerbaas.const import DOMAIN


class _FakeResponse:
    def __init__(self, json_data: Any) -> None:
        self._json_data = json_data

    def raise_for_status(self) -> None:
        return None

    async def json(self):
        return self._json_data


class _FakeGetContext:
    def __init__(self, response: _FakeResponse | None, exc: Exception | None) -> None:
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        if self._exc is not None:
            raise self._exc
        return self._response

    async def __aexit__(self, *_exc_info):
        return False


class _FakeSession:
    def __init__(self) -> None:
        self._queue: list[tuple[Any, Exception | None]] = []

    def queue_response(self, json_data: Any) -> None:
        self._queue.append((json_data, None))

    def get(self, url: str, timeout=None):  # noqa: ANN001
        json_data, exc = self._queue.pop(0) if self._queue else ({}, None)
        response = None if exc is not None else _FakeResponse(json_data)
        return _FakeGetContext(response, exc)


async def test_solar_sensors_live_on_their_own_device(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    session = _FakeSession()
    session.queue_response(
        {
            # Every MAIN_SENSORS/DIAGNOSTIC_SENSORS path populated - a
            # partial body would make those (unrelated) sensors raise while
            # HA writes their initial state, which isn't what this test is
            # about.
            "meterReading": {
                "powerUsage": 123,
                "powerDeliverHigh": 100,
                "powerDeliverLow": 100,
                "powerReturnHigh": 10,
                "powerReturnLow": 10,
                "gas": 50,
                "voltageL1": 230,
                "voltageL2": 230,
                "voltageL3": 230,
                "currentL1": 1,
                "currentL2": 1,
                "currentL3": 1,
                "powerUsageL1": 41,
                "powerUsageL2": 41,
                "powerUsageL3": 41,
            },
            "solarReading": {"current": 456, "total": 789000},
            "dynamicPrices": {"usage": 25, "return": 10},
            "system": {
                "wifiStrength": -60,
                "firmwareVersion": "1.0.0",
                "upSince": "2026-01-01 00:00:00",
                "ip": "192.168.1.100",
            },
        }
    )
    session.queue_response([])  # /api/battery - no batteries
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.async_get_clientsession",
        lambda _hass: session,
    )

    entry = MockConfigEntry(domain=DOMAIN, data={"host": "http://p1.local"}, title="P1 Meter")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    main_device = device_registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    solar_device = device_registry.async_get_device(
        identifiers={(DOMAIN, f"{entry.entry_id}_solar")}
    )
    assert main_device is not None
    assert solar_device is not None
    assert solar_device.id != main_device.id
    assert solar_device.name == "Solar"
    assert solar_device.via_device_id == main_device.id

    entity_registry = er.async_get(hass)
    power_entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_solarreading_current"
    )
    total_entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_solarreading_total"
    )
    assert power_entity_id is not None
    assert total_entity_id is not None
    assert entity_registry.entities[power_entity_id].device_id == solar_device.id
    assert entity_registry.entities[total_entity_id].device_id == solar_device.id

    assert hass.states.get(power_entity_id).state == "456.0"
