"""Tests for the Powerbaas PowerTemp async_setup_entry (coordinator wiring and offline detection)."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState, current_entry
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerbaas.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_POWER_TEMP,
    DOMAIN,
    OFFLINE_AFTER_CONSECUTIVE_FAILURES,
)
from custom_components.powerbaas.devices.power_temp import async_setup_entry
from custom_components.powerbaas.devices.power_temp.const import CONF_DEVICE_URL

SENSORS_RESPONSE = {
    "status": "ok",
    "deviceName": "Meterkast",
    "ambientC": 21.4,
    "temperatures": [
        {"port": 1, "type": "ds18b20", "name": "Groep 1", "configured": True, "enabled": True,
         "ambient": False, "present": True, "celsius": 28.3, "deltaC": 6.9, "status": "ok", "ageS": 2},
        {"port": 16, "type": "ntc", "name": "Ambient", "configured": True, "enabled": True,
         "ambient": True, "present": True, "celsius": 21.4, "deltaC": None, "status": "ok", "ageS": 2},
    ],
}
SYSTEM_RESPONSE = {"firmwareVersion": 3, "hostname": "pb-pt-aabbccddeeff", "ip": "192.168.1.20"}


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


class _FakeSession:
    """Serves queued responses/exceptions in order for every `.get()` call."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._queue: list[tuple[Any, int, Exception | None]] = []

    def queue_response(self, json_data: Any, status: int = 200) -> None:
        self._queue.append((json_data, status, None))

    def queue_exception(self, exc: Exception) -> None:
        self._queue.append((None, 0, exc))

    def get(self, url: str, timeout=None, params=None):  # noqa: ANN001
        self.calls.append(url)
        json_data, status, exc = self._queue.pop(0) if self._queue else ({}, 200, None)
        if exc is not None:
            raise exc
        return _FakeResponse(json_data, status)


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> _FakeSession:
    fake = _FakeSession()
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.power_temp.client.async_get_clientsession",
        lambda _hass: fake,
    )
    return fake


def _make_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_POWER_TEMP,
            CONF_DEVICE_URL: "http://pt.local",
            "device_id": "pb-pt-aabbccddeeff",
        },
        title="Powerbaas PowerTemp",
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    return entry


async def _setup(hass, session: _FakeSession):
    # test_connection -> /api/sensors; first refresh -> /api/sensors + /api/system
    session.queue_response(SENSORS_RESPONSE)
    session.queue_response(SENSORS_RESPONSE)
    session.queue_response(SYSTEM_RESPONSE)
    entry = _make_entry(hass)
    token = current_entry.set(entry)
    try:
        return await async_setup_entry(hass, entry)
    finally:
        current_entry.reset(token)


async def test_setup_indexes_ports_and_keeps_flat_system(hass, session) -> None:
    coordinator = (await _setup(hass, session))["coordinator"]

    assert set(coordinator.data["ports"]) == {1, 16}
    assert coordinator.data["ports"][1]["celsius"] == 28.3
    assert coordinator.data["system"]["firmwareVersion"] == 3
    assert coordinator.device_online is True
    assert session.calls == [
        "http://pt.local/api/sensors",
        "http://pt.local/api/sensors",
        "http://pt.local/api/system",
    ]


async def test_setup_raises_not_ready_when_unreachable(hass, session) -> None:
    session.queue_exception(aiohttp.ClientError("boom"))
    entry = _make_entry(hass)
    token = current_entry.set(entry)
    try:
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)
    finally:
        current_entry.reset(token)


async def test_listeners_notified_when_device_goes_offline_and_recovers(hass, session) -> None:
    coordinator = (await _setup(hass, session))["coordinator"]
    notified: list[bool] = []
    remove_listener = coordinator.async_add_listener(
        lambda: notified.append(coordinator.device_online)
    )

    for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
        session.queue_exception(aiohttp.ClientError("boom"))
        await coordinator.async_refresh()

    assert coordinator.device_online is False
    assert notified[-1] is False

    session.queue_response(SENSORS_RESPONSE)
    session.queue_response(SYSTEM_RESPONSE)
    await coordinator.async_refresh()

    assert coordinator.device_online is True
    assert notified[-1] is True
    remove_listener()
