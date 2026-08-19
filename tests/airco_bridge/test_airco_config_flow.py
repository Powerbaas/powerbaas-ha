"""Tests for the Airco Bridge config/options flow validation logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.powerbaas.const import CONF_DEVICE_TYPE, DEVICE_TYPE_AIRCO_BRIDGE
from custom_components.powerbaas.devices.airco_bridge.config_flow import (
    AircoBridgeFlowMixin,
    AircoBridgeOptionsFlow,
    _device_id_from_url,
)
from custom_components.powerbaas.devices.airco_bridge.const import CONF_DEVICE_URL


class _FakeFlow(AircoBridgeFlowMixin):
    """Minimal harness exposing only what the airco config steps touch."""

    def __init__(self) -> None:
        self.data: dict = {}
        self.unique_id = None
        self.created: dict | None = None
        self.shown: dict | None = None
        self.aborted: str | None = None
        self.hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda _domain: []))

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id

    def async_create_entry(self, *, title: str, data: dict):
        self.created = {"title": title, "data": data}
        return self.created

    def async_show_form(self, *, step_id: str, data_schema, errors: dict, description_placeholders=None):
        self.shown = {"step_id": step_id, "errors": errors}
        return self.shown

    def async_abort(self, *, reason: str):
        self.aborted = reason
        return {"reason": reason}

    def _abort_if_unique_id_configured(self, updates=None, **_kwargs):
        return None


async def test_async_step_airco_bridge_stores_name_and_continues() -> None:
    flow = _FakeFlow()
    flow._test_airco_connection = AsyncMock()

    result = await flow.async_step_airco_bridge({"name": "Woonkamer"})

    assert flow.data[CONF_DEVICE_TYPE] == DEVICE_TYPE_AIRCO_BRIDGE
    assert flow.data["name"] == "Woonkamer"
    assert result is flow.shown
    assert flow.shown["step_id"] == "airco_device_config"


async def test_async_step_airco_device_config_invalid_url_shows_error() -> None:
    flow = _FakeFlow()
    flow.data = {CONF_DEVICE_TYPE: DEVICE_TYPE_AIRCO_BRIDGE, "name": "Airco"}

    await flow.async_step_airco_device_config({CONF_DEVICE_URL: "not-a-url"})

    assert flow.shown["errors"] == {CONF_DEVICE_URL: "invalid_url"}
    assert flow.created is None


async def test_async_step_airco_device_config_cannot_connect_shows_error() -> None:
    flow = _FakeFlow()
    flow.data = {CONF_DEVICE_TYPE: DEVICE_TYPE_AIRCO_BRIDGE, "name": "Airco"}
    flow._test_airco_connection = AsyncMock(return_value=False)

    await flow.async_step_airco_device_config({CONF_DEVICE_URL: "http://airco.local"})

    assert flow.shown["errors"] == {CONF_DEVICE_URL: "cannot_connect_airco"}


async def test_async_step_airco_device_config_success_creates_entry() -> None:
    flow = _FakeFlow()
    flow.data = {CONF_DEVICE_TYPE: DEVICE_TYPE_AIRCO_BRIDGE, "name": "Woonkamer"}
    flow._test_airco_connection = AsyncMock(return_value=True)

    await flow.async_step_airco_device_config({CONF_DEVICE_URL: "http://airco.local/"})

    assert flow.created["title"] == "Woonkamer"
    assert flow.created["data"][CONF_DEVICE_URL] == "http://airco.local"
    assert flow.created["data"]["device_id"] == "airco.local"
    assert flow.unique_id == "airco_bridge:airco.local"


def test_device_id_from_url_includes_non_default_port() -> None:
    assert _device_id_from_url("http://airco.local/") == "airco.local"
    assert _device_id_from_url("http://host.docker.internal:18080") == "host.docker.internal:18080"
    assert _device_id_from_url("http://host.docker.internal:18081") == "host.docker.internal:18081"
    assert _device_id_from_url("http://192.168.2.3") == "192.168.2.3"


class _FakeOptionsFlow(AircoBridgeOptionsFlow):
    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry
        self.hass = SimpleNamespace(
            config_entries=SimpleNamespace(
                async_update_entry=lambda *a, **k: None,
                async_reload=AsyncMock(),
                async_entries=lambda _domain: [],
            )
        )
        self.created: dict | None = None
        self.shown: dict | None = None

    def async_create_entry(self, *, title: str, data: dict):
        self.created = {"title": title, "data": data}
        return self.created

    def async_show_form(self, *, step_id: str, data_schema, errors: dict, description_placeholders=None):
        self.shown = {"step_id": step_id, "errors": errors}
        return self.shown


async def test_options_flow_invalid_url_shows_error() -> None:
    entry = SimpleNamespace(
        data={CONF_DEVICE_URL: "http://old.local", "device_id": "old.local"},
        entry_id="airco_entry",
        unique_id="old.local",
    )
    flow = _FakeOptionsFlow(entry)

    await flow.async_step_airco_device_config({CONF_DEVICE_URL: "nope"})

    assert flow.shown["errors"] == {CONF_DEVICE_URL: "invalid_url"}


async def test_options_flow_success_updates_entry_and_reloads() -> None:
    entry = SimpleNamespace(
        data={CONF_DEVICE_URL: "http://old.local", "device_id": "old.local"},
        entry_id="airco_entry",
        unique_id="old.local",
    )
    flow = _FakeOptionsFlow(entry)
    flow._test_airco_connection = AsyncMock(return_value=True)

    await flow.async_step_airco_device_config({CONF_DEVICE_URL: "http://new.local"})

    assert flow.created == {"title": "", "data": {}}
    flow.hass.config_entries.async_reload.assert_awaited_once()
