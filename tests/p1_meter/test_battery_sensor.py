"""P1 meter battery devices: value lookup, and the create/rename/remove
lifecycle driven by battery_coordinator updates.

The lifecycle tests go through a real `hass.config_entries.async_setup()`
rather than building sensor objects via `object.__new__(...)` (the usual
convention - see docs/testing.md) because what's under test *is* the device
registry/entity registry side effects of `DeviceInfo` and
`Entity.async_remove()`/`device_registry.async_remove_device()` - those only
happen through the real entity platform machinery, so faking them away would
test nothing. Mirrors test_setup.py's similar exception for
DataUpdateCoordinator behavior.
"""

from __future__ import annotations

from typing import Any

import aiohttp
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerbaas.const import DOMAIN
from custom_components.powerbaas.devices.p1_meter.sensor import PowerBaasBatterySensor


# ---------------------------------------------------------------------------
# native_value lookup (by id, not list position) - plain object.__new__
# ---------------------------------------------------------------------------


def _battery_sensor(json_key: str, *, data: list[dict] | None) -> PowerBaasBatterySensor:
    from types import SimpleNamespace

    sensor = object.__new__(PowerBaasBatterySensor)
    sensor.coordinator = SimpleNamespace(data=data)
    sensor._battery_id = 2
    sensor._json_key = json_key
    return sensor


def test_native_value_matches_by_id_not_list_position() -> None:
    data = [
        {"id": 2, "product": "Zendure", "power": -417, "soc": 61.0},
        {"id": 1, "product": "Zendure", "power": 0, "soc": 60.0},
    ]
    sensor = _battery_sensor("power", data=data)

    assert PowerBaasBatterySensor.native_value.fget(sensor) == -417


def test_native_value_none_when_battery_id_missing() -> None:
    sensor = _battery_sensor("soc", data=[{"id": 1, "product": "Zendure", "power": 0, "soc": 60.0}])

    assert PowerBaasBatterySensor.native_value.fget(sensor) is None


def test_native_value_none_when_no_battery_data_yet() -> None:
    sensor = _battery_sensor("power", data=None)

    assert PowerBaasBatterySensor.native_value.fget(sensor) is None


# ---------------------------------------------------------------------------
# Create/rename/remove lifecycle - real config entry setup
# ---------------------------------------------------------------------------


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
    """Records every `.get()` call and serves queued responses/exceptions in order."""

    def __init__(self) -> None:
        self._queue: list[tuple[Any, Exception | None]] = []

    def queue_response(self, json_data: Any) -> None:
        self._queue.append((json_data, None))

    def queue_exception(self, exc: Exception) -> None:
        self._queue.append((None, exc))

    def get(self, url: str, timeout=None):  # noqa: ANN001
        json_data, exc = self._queue.pop(0) if self._queue else ({}, None)
        response = None if exc is not None else _FakeResponse(json_data)
        return _FakeGetContext(response, exc)


async def _setup_entry(hass, monkeypatch, session: _FakeSession) -> MockConfigEntry:
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.async_get_clientsession",
        lambda _hass: session,
    )
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "http://p1.local"}, title="P1 Meter")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _battery_device(hass, entry: MockConfigEntry, battery_id: int):
    registry = dr.async_get(hass)
    return registry.async_get_device(
        identifiers={(DOMAIN, f"{entry.entry_id}_battery_{battery_id}")}
    )


def _battery_entity_id(hass, entry: MockConfigEntry, battery_id: int, json_key: str) -> str | None:
    registry = er.async_get(hass)
    return registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_battery_{battery_id}_{json_key}"
    )


async def test_battery_devices_created_from_initial_poll(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {}})
    session.queue_response(
        [
            {"id": 1, "product": "Zendure", "power": 0, "soc": 60.0},
            {"id": 2, "product": "Zendure", "power": -417, "soc": 61.0},
        ]
    )

    entry = await _setup_entry(hass, monkeypatch, session)

    device_1 = _battery_device(hass, entry, 1)
    device_2 = _battery_device(hass, entry, 2)
    assert device_1 is not None
    assert device_2 is not None
    assert device_1.name == "Zendure"
    assert device_1.manufacturer == "Zendure"
    assert device_1.via_device_id == dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, entry.entry_id)}
    ).id

    assert _battery_entity_id(hass, entry, 1, "power") is not None
    assert _battery_entity_id(hass, entry, 1, "soc") is not None


async def test_missing_endpoint_creates_no_battery_devices(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {}})
    session.queue_exception(aiohttp.ClientError("boom"))

    entry = await _setup_entry(hass, monkeypatch, session)

    assert _battery_device(hass, entry, 1) is None
    # And the main P1 device/coordinator is unaffected by the battery failure.
    assert hass.data[DOMAIN][entry.entry_id]["coordinator"].device_online is True


async def test_product_rename_updates_device_registry_without_recreating_entities(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {}})
    session.queue_response([{"id": 1, "product": "Zendure", "power": 0, "soc": 60.0}])

    entry = await _setup_entry(hass, monkeypatch, session)
    battery_coordinator = hass.data[DOMAIN][entry.entry_id]["battery_coordinator"]
    power_entity_id_before = _battery_entity_id(hass, entry, 1, "power")

    session.queue_response([{"id": 1, "product": "Zendure SolarFlow 800", "power": 0, "soc": 60.0}])
    await battery_coordinator.async_refresh()
    await hass.async_block_till_done()

    device = _battery_device(hass, entry, 1)
    assert device.name == "Zendure SolarFlow 800"
    assert device.manufacturer == "Zendure SolarFlow 800"
    assert _battery_entity_id(hass, entry, 1, "power") == power_entity_id_before


async def test_battery_removed_from_successful_poll_removes_device_and_entities(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {}})
    session.queue_response(
        [
            {"id": 1, "product": "Zendure", "power": 0, "soc": 60.0},
            {"id": 2, "product": "Zendure", "power": -417, "soc": 61.0},
        ]
    )

    entry = await _setup_entry(hass, monkeypatch, session)
    battery_coordinator = hass.data[DOMAIN][entry.entry_id]["battery_coordinator"]
    assert _battery_entity_id(hass, entry, 2, "power") is not None

    session.queue_response([{"id": 1, "product": "Zendure", "power": 0, "soc": 60.0}])
    await battery_coordinator.async_refresh()
    await hass.async_block_till_done()

    assert _battery_device(hass, entry, 2) is None
    assert _battery_entity_id(hass, entry, 2, "power") is None
    assert _battery_entity_id(hass, entry, 2, "soc") is None
    # The still-present battery is untouched.
    assert _battery_device(hass, entry, 1) is not None
    assert _battery_entity_id(hass, entry, 1, "power") is not None


async def test_battery_appears_later_without_reload(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {}})
    session.queue_response([{"id": 1, "product": "Zendure", "power": 0, "soc": 60.0}])

    entry = await _setup_entry(hass, monkeypatch, session)
    battery_coordinator = hass.data[DOMAIN][entry.entry_id]["battery_coordinator"]
    assert _battery_device(hass, entry, 2) is None

    session.queue_response(
        [
            {"id": 1, "product": "Zendure", "power": 0, "soc": 60.0},
            {"id": 2, "product": "Zendure", "power": 5, "soc": 70.0},
        ]
    )
    await battery_coordinator.async_refresh()
    await hass.async_block_till_done()

    assert _battery_device(hass, entry, 2) is not None
    assert _battery_entity_id(hass, entry, 2, "power") is not None


async def test_failed_poll_does_not_remove_existing_battery(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {}})
    session.queue_response([{"id": 1, "product": "Zendure", "power": 0, "soc": 60.0}])

    entry = await _setup_entry(hass, monkeypatch, session)
    battery_coordinator = hass.data[DOMAIN][entry.entry_id]["battery_coordinator"]

    session.queue_exception(aiohttp.ClientError("boom"))
    await battery_coordinator.async_refresh()
    await hass.async_block_till_done()

    assert _battery_device(hass, entry, 1) is not None
    assert _battery_entity_id(hass, entry, 1, "power") is not None
