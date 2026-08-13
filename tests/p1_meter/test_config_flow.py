"""Tests for the P1 meter config/options flow validation logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol

from custom_components.powerbaas.devices.p1_meter.config_flow import (
    SCAN_INTERVAL_SCHEMA,
    P1MeterFlowMixin,
    P1MeterOptionsFlow,
    _is_valid_url,
)


# ---------------------------------------------------------------------------
# SCAN_INTERVAL_SCHEMA
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [5, 15, 60, "30"])
def test_scan_interval_schema_accepts_in_range_values(value) -> None:
    SCAN_INTERVAL_SCHEMA(value)  # must not raise


@pytest.mark.parametrize("value", [4, 61, -1, "not-a-number"])
def test_scan_interval_schema_rejects_out_of_range_or_uncoercible(value) -> None:
    with pytest.raises(vol.Invalid):
        SCAN_INTERVAL_SCHEMA(value)


# ---------------------------------------------------------------------------
# _is_valid_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["http://192.168.1.10", "http://powerbaas.local", "https://example.com/path"],
)
def test_is_valid_url_accepts_valid_urls(url: str) -> None:
    assert _is_valid_url(url) is True


@pytest.mark.parametrize("url", ["not-a-url", "", "192.168.1.10", "http://"])
def test_is_valid_url_rejects_invalid_urls(url: str) -> None:
    assert _is_valid_url(url) is False


# ---------------------------------------------------------------------------
# P1MeterFlowMixin.async_step_p1_meter
# ---------------------------------------------------------------------------


class _FakeFlow(P1MeterFlowMixin):
    """Minimal harness exposing only what async_step_p1_meter touches."""

    def __init__(self) -> None:
        self.data: dict = {}
        self.created: dict | None = None
        self.shown: dict | None = None

    def async_create_entry(self, *, title: str, data: dict):
        self.created = {"title": title, "data": data}
        return self.created

    def async_show_form(self, *, step_id: str, data_schema, errors: dict):
        self.shown = {"step_id": step_id, "errors": errors}
        return self.shown


async def test_async_step_p1_meter_invalid_host_shows_error() -> None:
    flow = _FakeFlow()

    result = await flow.async_step_p1_meter({"host": "not-a-url", "name": "P1"})

    assert flow.shown["errors"] == {"host": "invalid_host"}
    assert flow.created is None
    assert result is flow.shown


async def test_async_step_p1_meter_cannot_connect_shows_error() -> None:
    flow = _FakeFlow()

    with patch(
        "custom_components.powerbaas.devices.p1_meter.config_flow._test_connection",
        AsyncMock(return_value=False),
    ):
        await flow.async_step_p1_meter({"host": "http://p1.local", "name": "P1"})

    assert flow.shown["errors"] == {"host": "cannot_connect"}


async def test_async_step_p1_meter_success_creates_entry() -> None:
    flow = _FakeFlow()

    with patch(
        "custom_components.powerbaas.devices.p1_meter.config_flow._test_connection",
        AsyncMock(return_value=True),
    ):
        await flow.async_step_p1_meter({"host": "http://p1.local/", "name": "My P1"})

    assert flow.created["title"] == "My P1"
    assert flow.created["data"]["host"] == "http://p1.local"


# ---------------------------------------------------------------------------
# P1MeterOptionsFlow.async_step_p1_meter_init
# ---------------------------------------------------------------------------


class _FakeOptionsFlow(P1MeterOptionsFlow):
    """`OptionsFlow.config_entry` is a read-only property (derived from
    `hass.config_entries.async_get_known_entry`) in this HA version, so it's
    overridden here rather than assigned directly.
    """

    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry
        self.hass = SimpleNamespace(
            config_entries=SimpleNamespace(
                async_update_entry=lambda *a, **k: None,
                async_reload=AsyncMock(),
            )
        )
        self.created: dict | None = None
        self.shown: dict | None = None

    @property
    def config_entry(self):
        return self._config_entry

    def async_create_entry(self, *, title: str, data: dict):
        self.created = {"title": title, "data": data}
        return self.created

    def async_show_form(self, *, step_id: str, data_schema, errors: dict):
        self.shown = {"step_id": step_id, "errors": errors}
        return self.shown


async def test_options_flow_invalid_host_shows_error() -> None:
    entry = SimpleNamespace(
        data={"host": "http://old.local", "scan_interval": 15}, entry_id="p1_entry"
    )
    flow = _FakeOptionsFlow(entry)

    await flow.async_step_p1_meter_init({"host": "nope", "scan_interval": 15})

    assert flow.shown["errors"] == {"host": "invalid_host"}


async def test_options_flow_success_updates_entry_and_reloads() -> None:
    entry = SimpleNamespace(
        data={"host": "http://old.local", "scan_interval": 15}, entry_id="p1_entry"
    )
    flow = _FakeOptionsFlow(entry)

    with patch(
        "custom_components.powerbaas.devices.p1_meter.config_flow._test_connection",
        AsyncMock(return_value=True),
    ):
        await flow.async_step_p1_meter_init({"host": "http://new.local", "scan_interval": 30})

    assert flow.created == {"title": "", "data": {}}
    flow.hass.config_entries.async_reload.assert_awaited_once()
