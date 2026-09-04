"""Tests for the P1 meter's async_setup_entry (coordinator wiring, timeout
clamping, offline detection) and migrate_legacy_entities.

async_update_data/request_timeout are computed inline inside
async_setup_entry rather than exposed as standalone functions, so these are
exercised end-to-end against a fake aiohttp session (patched in place of
async_get_clientsession) plus the real `hass` fixture - DataUpdateCoordinator
needs a real event loop/hass to schedule refreshes against.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState, current_entry
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerbaas.const import DOMAIN, OFFLINE_AFTER_CONSECUTIVE_FAILURES
from custom_components.powerbaas.devices.p1_meter import (
    async_setup_entry,
    migrate_legacy_entities,
)
from custom_components.powerbaas.devices.p1_meter.const import (
    BATTERY_SCAN_INTERVAL,
    MAX_TIMEOUT,
    MIN_TIMEOUT,
    TIMEOUT_RATIO,
)


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
        self.calls: list[dict[str, Any]] = []
        self._queue: list[tuple[Any, Exception | None]] = []

    def queue_response(self, json_data: Any) -> None:
        self._queue.append((json_data, None))

    def queue_exception(self, exc: Exception) -> None:
        self._queue.append((None, exc))

    def get(self, url: str, timeout=None):  # noqa: ANN001
        self.calls.append({"url": url, "timeout": timeout})
        json_data, exc = self._queue.pop(0) if self._queue else ({}, None)
        response = None if exc is not None else _FakeResponse(json_data)
        return _FakeGetContext(response, exc)


def _make_entry(hass, *, host: str = "http://p1.local", scan_interval: int | None = None):
    """A real MockConfigEntry, set to SETUP_IN_PROGRESS.

    DataUpdateCoordinator.async_config_entry_first_refresh() requires a
    config entry to be resolvable (either passed explicitly - which this
    integration's async_setup_entry does not do - or via the
    `current_entry` ContextVar that Home Assistant's own config-entry setup
    machinery sets around the call to a platform's async_setup_entry). Tests
    call async_setup_entry() directly rather than through that machinery, so
    _call_async_setup_entry() below sets the ContextVar itself.
    """
    data: dict[str, Any] = {"host": host}
    if scan_interval is not None:
        data["scan_interval"] = scan_interval
    entry = MockConfigEntry(domain=DOMAIN, data=data, title="P1 Meter")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    return entry


async def _call_async_setup_entry(hass, entry):
    token = current_entry.set(entry)
    try:
        return await async_setup_entry(hass, entry)
    finally:
        current_entry.reset(token)


@pytest.mark.parametrize(
    ("scan_interval", "expected_timeout"),
    [
        (5, MIN_TIMEOUT),  # 5 * 0.6 = 3.0, clamps to MIN_TIMEOUT (3)
        (60, MAX_TIMEOUT),  # 60 * 0.6 = 36, clamps to MAX_TIMEOUT (10)
        (15, 15 * TIMEOUT_RATIO),  # 9.0, within range untouched
    ],
)
async def test_request_timeout_is_clamped_to_scan_interval(
    hass, monkeypatch: pytest.MonkeyPatch, scan_interval: int, expected_timeout: float
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {}})
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.async_get_clientsession",
        lambda _hass: session,
    )

    await _call_async_setup_entry(hass, _make_entry(hass, scan_interval=scan_interval))

    assert session.calls[0]["timeout"].total == expected_timeout


async def test_async_setup_entry_returns_working_coordinator(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {"powerUsage": 123}})
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))

    coordinator = result["coordinator"]
    assert coordinator.data == {"meterReading": {"powerUsage": 123}}
    assert coordinator.device_online is True


async def test_async_setup_entry_raises_config_entry_not_ready_on_first_failure(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    from homeassistant.exceptions import ConfigEntryNotReady

    session = _FakeSession()
    session.queue_exception(aiohttp.ClientError("boom"))
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.async_get_clientsession",
        lambda _hass: session,
    )

    with pytest.raises(ConfigEntryNotReady):
        await _call_async_setup_entry(hass, _make_entry(hass))


async def test_coordinator_goes_offline_after_consecutive_failures(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {}})
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.async_get_clientsession",
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
    session.queue_response({"meterReading": {}})
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))
    coordinator = result["coordinator"]

    for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
        session.queue_exception(aiohttp.ClientError("boom"))
        await coordinator.async_refresh()
    assert coordinator.device_online is False

    session.queue_response({"meterReading": {}})
    await coordinator.async_refresh()

    assert coordinator.device_online is True


# ---------------------------------------------------------------------------
# battery_coordinator - see p1_meter/const.py's BATTERY_API_PATH
# ---------------------------------------------------------------------------


async def test_battery_coordinator_parses_valid_response(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {}})
    session.queue_response([{"id": 1, "product": "Zendure", "power": 0, "soc": 60.0}])
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))

    battery_coordinator = result["battery_coordinator"]
    assert battery_coordinator.data == [{"id": 1, "product": "Zendure", "power": 0, "soc": 60.0}]
    assert session.calls[1]["url"] == "http://p1.local/api/battery"


async def test_battery_coordinator_polls_at_fixed_interval_not_scan_interval(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {}})
    session.queue_response([])
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass, scan_interval=5))

    assert result["battery_coordinator"].update_interval == timedelta(seconds=BATTERY_SCAN_INTERVAL)
    assert result["coordinator"].update_interval == timedelta(seconds=5)


async def test_battery_coordinator_treats_failure_as_empty_without_raising(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {}})
    session.queue_exception(aiohttp.ClientError("boom"))
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))

    assert result["battery_coordinator"].data == []
    # The battery endpoint failing must not affect the main coordinator/offline state.
    assert result["coordinator"].device_online is True


async def test_battery_coordinator_treats_non_list_response_as_empty(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {}})
    session.queue_response({"error": "not found"})
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))

    assert result["battery_coordinator"].data == []


async def test_battery_coordinator_keeps_previous_data_on_later_failure(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession()
    session.queue_response({"meterReading": {}})
    session.queue_response([{"id": 1, "product": "Zendure", "power": 10, "soc": 50.0}])
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.async_get_clientsession",
        lambda _hass: session,
    )

    result = await _call_async_setup_entry(hass, _make_entry(hass))
    battery_coordinator = result["battery_coordinator"]
    assert len(battery_coordinator.data) == 1

    session.queue_exception(aiohttp.ClientError("boom"))
    await battery_coordinator.async_refresh()

    assert battery_coordinator.data == [{"id": 1, "product": "Zendure", "power": 10, "soc": 50.0}]


# ---------------------------------------------------------------------------
# migrate_legacy_entities
# ---------------------------------------------------------------------------


async def test_migrate_legacy_entities_rewrites_old_unique_id(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    reg_entry = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_meterReading.powerUsage",
        config_entry=entry,
    )

    migrate_legacy_entities(hass, entry)

    updated = registry.async_get(reg_entry.entity_id)
    assert updated.unique_id == f"{entry.entry_id}_meterReading.powerUsage"


async def test_migrate_legacy_entities_leaves_already_migrated_entities_alone(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    already_migrated_unique_id = f"{entry.entry_id}_meterReading.powerUsage"
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        already_migrated_unique_id,
        config_entry=entry,
    )

    migrate_legacy_entities(hass, entry)

    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert [e.unique_id for e in entities] == [already_migrated_unique_id]


async def test_migrate_legacy_entities_ignores_other_platforms(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    other_platform_unique_id = f"{DOMAIN}_some_legacy_id"
    reg_entry = registry.async_get_or_create(
        "sensor",
        "some_other_platform",
        other_platform_unique_id,
        config_entry=entry,
    )

    migrate_legacy_entities(hass, entry)

    updated = registry.async_get(reg_entry.entity_id)
    assert updated.unique_id == other_platform_unique_id
