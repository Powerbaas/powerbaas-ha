"""Tests for the Boiler Controller async_setup_entry (coordinator wiring and offline detection)."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState, current_entry
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerbaas.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_BOILER_CONTROLLER,
    DOMAIN,
    OFFLINE_AFTER_CONSECUTIVE_FAILURES,
)
from custom_components.powerbaas.devices.boiler_controller import async_setup_entry
from custom_components.powerbaas.devices.boiler_controller.const import (
    BOILER_MODE_MANUAL,
    CONF_DEVICE_URL,
    CONF_POWER_SENSOR,
    CONF_POWER_SENSOR_TYPE,
    POWER_SENSOR_TYPE_NET,
)


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
    """Serves queued responses/exceptions in order for every .get()/.post() call."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._queue: list[tuple[Any, int, Exception | None]] = []

    def queue_response(self, json_data: Any, status: int = 200) -> None:
        self._queue.append((json_data, status, None))

    def queue_exception(self, exc: Exception) -> None:
        self._queue.append((None, 0, exc))

    def _next(self, url: str) -> _FakeResponse:
        self.calls.append(url)
        json_data, status, exc = self._queue.pop(0) if self._queue else ({}, 200, None)
        if exc is not None:
            raise exc
        return _FakeResponse(json_data, status)

    def get(self, url: str, timeout=None, params=None):  # noqa: ANN001
        return self._next(url)

    def post(self, url: str, timeout=None, json=None):  # noqa: ANN001
        return self._next(url)


def _make_entry(
    hass,
    *,
    device_url: str = "http://bc.local",
    power_sensor: str = "sensor.net_power",
    options: dict | None = None,
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE_TYPE: DEVICE_TYPE_BOILER_CONTROLLER,
            CONF_DEVICE_URL: device_url,
            CONF_POWER_SENSOR_TYPE: POWER_SENSOR_TYPE_NET,
            CONF_POWER_SENSOR: power_sensor,
            "device_id": "pb-bc-test",
        },
        options=options or {},
        title="Test BC",
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
    session.queue_response({"power": 0, "heatingPercentage": 0, "maxHeatingWatts": 2000})
    # first refresh: /api/system then /api/status. heatingPercentage=0
    # matches the default "off" mode's target, so no POST follows during the
    # setup-time initial control tick.
    session.queue_response({"system": {"firmwareVersion": 9, "ip": "192.168.1.10"}})
    session.queue_response({"power": 0, "heatingPercentage": 0, "maxHeatingWatts": 2000})


async def test_async_setup_entry_returns_working_coordinator(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    _queue_successful_setup(session)
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.bc_client.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))

    coordinator = result["coordinator"]
    assert coordinator.data["status"]["maxHeatingWatts"] == 2000
    assert coordinator.data["system"]["firmwareVersion"] == 9
    assert coordinator.data["max_heating_watts"] == 2000
    assert coordinator.device_online is True


async def test_async_setup_entry_raises_config_entry_not_ready_on_first_failure(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    session.queue_exception(aiohttp.ClientError("boom"))
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.bc_client.async_get_clientsession",
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
        "custom_components.powerbaas.devices.boiler_controller.bc_client.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))
    coordinator = result["coordinator"]
    assert coordinator.device_online is True

    for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
        # Each refresh cycle issues /api/system then /api/status.
        session.queue_exception(aiohttp.ClientError("boom"))
        session.queue_exception(aiohttp.ClientError("boom"))
        await coordinator.async_refresh()

    assert coordinator.device_online is False
    assert coordinator.data["status"] is None
    assert coordinator.data["system"] is None
    # Command-driven fields survive the offline-threshold clear.
    assert coordinator.data["control_mode"] == "off"


async def test_coordinator_recovers_after_successful_fetch(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    _queue_successful_setup(session)
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.bc_client.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))
    coordinator = result["coordinator"]

    for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
        session.queue_exception(aiohttp.ClientError("boom"))
        session.queue_exception(aiohttp.ClientError("boom"))
        await coordinator.async_refresh()
    assert coordinator.device_online is False

    session.queue_response({"system": {"firmwareVersion": 9}})
    session.queue_response({"power": 0, "heatingPercentage": 0, "maxHeatingWatts": 2000})
    await coordinator.async_refresh()

    assert coordinator.device_online is True


async def test_command_driven_fields_survive_a_poll_cycle(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_async_update_data() must carry forward control_mode/target_watts/etc.

    from the previous cycle, since they aren't re-fetched from the device -
    forgetting this would wipe them back to defaults every poll.
    """
    session = _FakeSession()
    _queue_successful_setup(session)
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.bc_client.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))
    coordinator = result["coordinator"]
    coordinator.data = {**coordinator.data, "control_mode": BOILER_MODE_MANUAL, "target_watts": 500}

    session.queue_response({"system": {"firmwareVersion": 9}})
    session.queue_response({"power": 0, "heatingPercentage": 0, "maxHeatingWatts": 2000})
    await coordinator.async_refresh()

    assert coordinator.data["control_mode"] == BOILER_MODE_MANUAL
    assert coordinator.data["target_watts"] == 500


async def test_target_watts_restored_from_options_on_setup(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    """target_watts isn't restored on every write (see coordinator.py), only

    persisted once on HA shutdown - so setup must read that persisted value
    back, otherwise a restart would silently reset it to the default.
    """
    session = _FakeSession()
    _queue_successful_setup(session)
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.bc_client.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(
        hass, _make_entry(hass, options={"target_watts": 500})
    )

    assert result["coordinator"].data["target_watts"] == 500


async def test_target_watts_persisted_on_homeassistant_stop(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EVENT_HOMEASSISTANT_STOP must flush the current target_watts to the

    config entry options so it survives the restart - see
    async_persist_target_watts_on_stop() and its wiring in __init__.py.
    Only meaningful in Manual mode - see that method's docstring for why.
    """
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP

    session = _FakeSession()
    _queue_successful_setup(session)
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.bc_client.async_get_clientsession",
        lambda _hass: session,
    )

    entry = _make_entry(hass)
    result = await _call_async_setup_entry(hass, entry)
    coordinator = result["coordinator"]
    coordinator.data = {
        **coordinator.data,
        "control_mode": BOILER_MODE_MANUAL,
        "target_watts": 750,
    }

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()

    assert entry.options["target_watts"] == 750


async def test_max_heating_watts_cascade_clamps_min_inside_update_data(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The device is the source of truth for maxHeatingWatts; a poll that
    reports a lower max must clamp min_heating_watts down too, in the same
    cycle - not just when the max-watts select is used directly.
    """
    session = _FakeSession()
    _queue_successful_setup(session)
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.boiler_controller.bc_client.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))
    coordinator = result["coordinator"]
    coordinator.data = {**coordinator.data, "min_heating_watts": 1800}

    session.queue_response({"system": {"firmwareVersion": 9}})
    session.queue_response({"power": 0, "heatingPercentage": 0, "maxHeatingWatts": 1000})
    await coordinator.async_refresh()

    assert coordinator.data["max_heating_watts"] == 1000
    assert coordinator.data["min_heating_watts"] == 1000
