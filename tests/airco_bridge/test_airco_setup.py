"""Tests for the Airco Bridge async_setup_entry (coordinator wiring and offline detection)."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState, current_entry
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerbaas.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_AIRCO_BRIDGE,
    DOMAIN,
    OFFLINE_AFTER_CONSECUTIVE_FAILURES,
)
from custom_components.powerbaas.devices.airco_bridge import async_setup_entry
from custom_components.powerbaas.devices.airco_bridge.const import CONF_DEVICE_URL


class _FakeResponse:
    def __init__(self, json_data: Any, status: int = 200) -> None:
        self.status = status
        self._json_data = json_data

    async def json(self, content_type=None):  # noqa: ANN001
        return self._json_data

    async def text(self):
        return ""

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


def _make_entry(hass, *, device_url: str = "http://airco.local"):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_AIRCO_BRIDGE,
            CONF_DEVICE_URL: device_url,
            "device_id": "pb-airco-test",
        },
        title="Airco Bridge",
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    return entry


async def _call_async_setup_entry(hass, entry):
    token = current_entry.set(entry)
    try:
        return await async_setup_entry(hass, entry)
    finally:
        current_entry.reset(token)


def _queue_successful_setup(session: _FakeSession) -> None:
    # test_connection -> /api/status
    session.queue_response({"airco": {"ison": True, "mode": 1, "degrees": 21, "fanspeed": 0, "type": 14}})
    # async_get_types -> /types
    session.queue_response({"types": [{"key": "DAIKIN", "value": 14}]})
    # first refresh: /api/status then /api/system
    session.queue_response({"airco": {"ison": True, "mode": 1, "degrees": 21, "fanspeed": 0, "type": 14}})
    session.queue_response({"system": {"firmwareVersion": 9, "ip": "192.168.1.10"}})


async def test_async_setup_entry_returns_working_coordinator(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    _queue_successful_setup(session)
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.airco_bridge.client.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))

    coordinator = result["coordinator"]
    assert coordinator.data["airco"]["mode"] == 1
    assert coordinator.data["system"]["firmwareVersion"] == 9
    assert coordinator.device_online is True
    assert coordinator.ir_types == [{"key": "DAIKIN", "value": 14}]


async def test_async_setup_entry_raises_config_entry_not_ready_on_first_failure(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    session.queue_exception(aiohttp.ClientError("boom"))
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.airco_bridge.client.async_get_clientsession",
        lambda _hass: session,
    )

    with pytest.raises(ConfigEntryNotReady):
        await _call_async_setup_entry(hass, _make_entry(hass))


async def test_coordinator_goes_offline_after_consecutive_failures(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    _queue_successful_setup(session)
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.airco_bridge.client.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))
    coordinator = result["coordinator"]
    assert coordinator.device_online is True

    for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
        session.queue_exception(aiohttp.ClientError("boom"))
        await coordinator.async_refresh()

    assert coordinator.device_online is False


async def test_coordinator_recovers_after_successful_fetch(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    _queue_successful_setup(session)
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.airco_bridge.client.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))
    coordinator = result["coordinator"]

    for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
        session.queue_exception(aiohttp.ClientError("boom"))
        await coordinator.async_refresh()
    assert coordinator.device_online is False

    session.queue_response({"airco": {"ison": False}})
    session.queue_response({"system": {"firmwareVersion": 9}})
    await coordinator.async_refresh()

    assert coordinator.device_online is True


async def test_listeners_notified_when_device_goes_offline(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Entities (via CoordinatorEntity) only learn about device_online
    flipping through the coordinator's listener callback - HA's
    DataUpdateCoordinator only calls that callback for the *first* failed
    refresh after a success, so registering the offline flag on a later
    consecutive failure must explicitly notify listeners itself, or
    entities never find out and stay stuck showing "available".
    """
    session = _FakeSession()
    _queue_successful_setup(session)
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.airco_bridge.client.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))
    coordinator = result["coordinator"]

    observed_online_states: list[bool] = []
    remove_listener = coordinator.async_add_listener(
        lambda: observed_online_states.append(coordinator.device_online)
    )
    try:
        for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
            session.queue_exception(aiohttp.ClientError("boom"))
            await coordinator.async_refresh()
    finally:
        remove_listener()

    assert coordinator.device_online is False
    assert False in observed_online_states
