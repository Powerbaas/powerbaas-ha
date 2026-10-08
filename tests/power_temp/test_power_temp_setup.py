"""Tests for the Powerbaas PowerTemp async_setup_entry (coordinator wiring, offline detection, new-sensor issues)."""

from __future__ import annotations

import copy
from typing import Any

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState, current_entry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerbaas.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_POWER_TEMP,
    DOMAIN,
    OFFLINE_AFTER_CONSECUTIVE_FAILURES,
)
from custom_components.powerbaas.devices.power_temp import async_setup_entry, new_sensor_issue_id
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
NEW_PORT_5 = {"port": 5, "type": "ntc", "name": "", "configured": False, "enabled": True,
              "ambient": False, "present": True, "celsius": 30.1, "deltaC": 8.7, "status": "ok", "ageS": 1}
SYSTEM_RESPONSE = {"firmwareVersion": 3, "hostname": "pb-pt-aabbccddeeff", "ip": "192.168.1.20"}
CONFIG_RESPONSE = {
    "deviceName": "Meterkast",
    "pollIntervalS": 10,
    "thresholds": {"warnC": 45, "alarmC": 60, "hysteresisC": 2},
    "delta": {"enabled": True, "warnC": 10, "alarmC": 20},
    "sensors": [
        {"port": 1, "name": "Groep 1", "offsetC": 0, "enabled": True, "ambient": False},
        {"port": 16, "name": "Ambient", "offsetC": 0, "enabled": True, "ambient": True},
    ],
}


def _sensors_with(*extra: dict) -> dict:
    data = copy.deepcopy(SENSORS_RESPONSE)
    data["temperatures"].extend(copy.deepcopy(item) for item in extra)
    return data


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

    def queue_poll(self, sensors: dict = SENSORS_RESPONSE) -> None:
        """One coordinator refresh: /api/sensors, /api/system, /api/config."""
        self.queue_response(sensors)
        self.queue_response(SYSTEM_RESPONSE)
        self.queue_response(CONFIG_RESPONSE)

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


async def _setup(hass, session: _FakeSession, sensors: dict = SENSORS_RESPONSE):
    session.queue_response(sensors)  # test_connection
    session.queue_poll(sensors)  # first refresh
    entry = _make_entry(hass)
    token = current_entry.set(entry)
    try:
        return entry, (await async_setup_entry(hass, entry))["coordinator"]
    finally:
        current_entry.reset(token)


async def test_setup_indexes_ports_and_polls_config(hass, session) -> None:
    _, coordinator = await _setup(hass, session)

    assert set(coordinator.data["ports"]) == {1, 16}
    assert coordinator.data["ports"][1]["celsius"] == 28.3
    assert coordinator.data["system"]["firmwareVersion"] == 3
    assert coordinator.data["config"]["thresholds"]["warnC"] == 45
    assert coordinator.device_online is True
    assert session.calls == [
        "http://pt.local/api/sensors",
        "http://pt.local/api/sensors",
        "http://pt.local/api/system",
        "http://pt.local/api/config",
    ]


async def test_failed_config_poll_keeps_last_known_config(hass, session) -> None:
    _, coordinator = await _setup(hass, session)

    session.queue_response(SENSORS_RESPONSE)
    session.queue_response(SYSTEM_RESPONSE)
    session.queue_exception(aiohttp.ClientError("boom"))
    await coordinator.async_refresh()

    assert coordinator.data["config"]["thresholds"]["warnC"] == 45


async def test_setup_raises_not_ready_when_unreachable(hass, session) -> None:
    session.queue_exception(aiohttp.ClientError("boom"))
    entry = _make_entry(hass)
    token = current_entry.set(entry)
    try:
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)
    finally:
        current_entry.reset(token)


async def test_new_sensor_issue_raised_and_cleared_once_configured(hass, session) -> None:
    entry, coordinator = await _setup(hass, session, _sensors_with(NEW_PORT_5))
    issue_id = new_sensor_issue_id(entry.entry_id, 5)
    registry = issue_registry.async_get(hass)

    issue = registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.data == {"entry_id": entry.entry_id, "port": 5}

    session.queue_poll(_sensors_with({**NEW_PORT_5, "configured": True, "name": "Groep 5"}))
    await coordinator.async_refresh()

    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_new_sensor_issue_stays_while_missing_and_clears_once_forgotten(hass, session) -> None:
    # The firmware keeps listing a failed, unconfigured sensor as "missing"
    # for a while; the adopt issue must not silently disappear meanwhile.
    entry, coordinator = await _setup(hass, session, _sensors_with(NEW_PORT_5))
    registry = issue_registry.async_get(hass)
    issue_id = new_sensor_issue_id(entry.entry_id, 5)

    session.queue_poll(_sensors_with({**NEW_PORT_5, "present": False, "celsius": None, "status": "missing"}))
    await coordinator.async_refresh()
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    session.queue_poll(SENSORS_RESPONSE)
    await coordinator.async_refresh()
    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_ignored_port_raises_no_issue_until_replugged(hass, session) -> None:
    missing_5 = {**NEW_PORT_5, "present": False, "celsius": None, "status": "missing"}
    entry, coordinator = await _setup(hass, session, _sensors_with(missing_5))
    registry = issue_registry.async_get(hass)
    issue_id = new_sensor_issue_id(entry.entry_id, 5)
    coordinator.ignored_ports.add(5)

    session.queue_poll(_sensors_with(missing_5))
    await coordinator.async_refresh()
    assert registry.async_get_issue(DOMAIN, issue_id) is None

    session.queue_poll(_sensors_with(NEW_PORT_5))
    await coordinator.async_refresh()
    assert 5 not in coordinator.ignored_ports
    assert registry.async_get_issue(DOMAIN, issue_id) is not None


async def test_listeners_notified_when_device_goes_offline_and_recovers(hass, session) -> None:
    _, coordinator = await _setup(hass, session)
    notified: list[bool] = []
    remove_listener = coordinator.async_add_listener(
        lambda: notified.append(coordinator.device_online)
    )

    for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
        session.queue_exception(aiohttp.ClientError("boom"))
        await coordinator.async_refresh()

    assert coordinator.device_online is False
    assert notified[-1] is False

    session.queue_poll()
    await coordinator.async_refresh()

    assert coordinator.device_online is True
    assert notified[-1] is True
    remove_listener()
