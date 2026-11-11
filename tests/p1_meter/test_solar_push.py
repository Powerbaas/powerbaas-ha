"""Solar from Home Assistant -> P1 meter: a local-only webhook that serves
{"current": W, "total": Wh} from two HA sensors, for the P1 firmware's
custom solar integration (see p1_meter/solar_push.py).
"""

from __future__ import annotations

import json
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components import webhook
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerbaas.const import DOMAIN
from custom_components.powerbaas.devices.p1_meter import solar_push
from custom_components.powerbaas.devices.p1_meter.config_flow import (
    P1MeterFlowMixin,
    P1MeterOptionsFlow,
)
from custom_components.powerbaas.devices.p1_meter.const import (
    CONF_SOLAR_ENERGY_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    CONF_SOLAR_PUSH_ENABLED,
    CONF_SOLAR_WEBHOOK_ID,
)

POWER = "sensor.inverter_power"
ENERGY = "sensor.inverter_energy"
WEBHOOK_ID = "0123456789abcdef0123456789abcdef"


def _set_sources(hass, power="2340", power_unit="W", energy="15234", energy_unit="kWh") -> None:
    hass.states.async_set(POWER, power, {"unit_of_measurement": power_unit})
    hass.states.async_set(ENERGY, energy, {"unit_of_measurement": energy_unit})


# ---------------------------------------------------------------------------
# build_payload
# ---------------------------------------------------------------------------


async def test_payload_in_w_and_wh(hass) -> None:
    _set_sources(hass, power="2340", power_unit="W", energy="15234000", energy_unit="Wh")

    assert solar_push.build_payload(hass, POWER, ENERGY) == {"current": 2340, "total": 15234000}


async def test_payload_converts_kw_and_kwh(hass) -> None:
    _set_sources(hass, power="2.34", power_unit="kW", energy="15234.5", energy_unit="kWh")

    assert solar_push.build_payload(hass, POWER, ENERGY) == {"current": 2340, "total": 15234500}


@pytest.mark.parametrize(
    ("power", "power_unit", "energy", "energy_unit"),
    [
        ("unavailable", "W", "1", "kWh"),
        ("1", "W", "unknown", "kWh"),
        ("not-a-number", "W", "1", "kWh"),
        ("1", "°C", "1", "kWh"),  # unit that isn't power
        ("1", "W", "1", None),  # no unit at all
    ],
)
async def test_payload_none_when_a_source_cannot_be_read(
    hass, power, power_unit, energy, energy_unit
) -> None:
    _set_sources(hass, power=power, power_unit=power_unit, energy=energy, energy_unit=energy_unit)

    assert solar_push.build_payload(hass, POWER, ENERGY) is None


async def test_payload_none_when_a_source_does_not_exist(hass) -> None:
    hass.states.async_set(POWER, "100", {"unit_of_measurement": "W"})

    assert solar_push.build_payload(hass, POWER, ENERGY) is None


# ---------------------------------------------------------------------------
# Webhook end-to-end, through a real P1 entry setup
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, json_data: Any) -> None:
        self._json_data = json_data

    def raise_for_status(self) -> None:
        return None

    async def json(self):
        return self._json_data


class _FakeGetContext:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *_exc_info):
        return False


class _FakeSession:
    """Answers the meter endpoint with a full reading and /api/battery with []."""

    METER = {
        "meterReading": {
            key: 1
            for key in (
                "powerUsage", "powerDeliverHigh", "powerDeliverLow", "powerReturnHigh",
                "powerReturnLow", "gas", "voltageL1", "voltageL2", "voltageL3",
                "currentL1", "currentL2", "currentL3", "powerUsageL1", "powerUsageL2",
                "powerUsageL3",
            )
        },
        "solarReading": {"current": 0, "total": 0},
        "dynamicPrices": {"usage": 25, "return": 10},
        "system": {
            "wifiStrength": -60,
            "firmwareVersion": "1.0.0",
            "upSince": "2026-01-01 00:00:00",
            "ip": "192.168.1.100",
        },
    }

    def get(self, url: str, timeout=None):  # noqa: ANN001
        return _FakeGetContext(_FakeResponse([] if url.endswith("/api/battery") else self.METER))


async def _setup_p1(hass, monkeypatch, **data) -> MockConfigEntry:
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.async_get_clientsession",
        lambda _hass: _FakeSession(),
    )
    entry = MockConfigEntry(
        domain=DOMAIN, data={"host": "http://p1.local", **data}, title="P1 Meter"
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _request(hass, method="GET", remote="127.0.0.1"):
    """What HA's /api/webhook/<id> view does with a request, without opening a socket."""
    request = MagicMock(remote=remote, method=method)
    request.content.read = AsyncMock(return_value=b"")
    return await webhook.async_handle_webhook(hass, WEBHOOK_ID, request)


SOLAR_DATA = {
    CONF_SOLAR_PUSH_ENABLED: True,
    CONF_SOLAR_POWER_ENTITY: POWER,
    CONF_SOLAR_ENERGY_ENTITY: ENERGY,
    CONF_SOLAR_WEBHOOK_ID: WEBHOOK_ID,
}


async def test_webhook_serves_solar_json(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    _set_sources(hass, power="1.5", power_unit="kW", energy="12.345", energy_unit="kWh")
    await _setup_p1(hass, monkeypatch, **SOLAR_DATA)

    response = await _request(hass)

    assert response.status == HTTPStatus.OK
    assert json.loads(response.body) == {"current": 1500, "total": 12345}


async def test_webhook_503_while_a_source_is_unavailable(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    _set_sources(hass)
    await _setup_p1(hass, monkeypatch, **SOLAR_DATA)
    hass.states.async_set(POWER, "unavailable")

    response = await _request(hass)

    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE


async def test_webhook_only_accepts_get(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    _set_sources(hass)
    await _setup_p1(hass, monkeypatch, **SOLAR_DATA)

    response = await _request(hass, method="POST")

    assert response.status == HTTPStatus.METHOD_NOT_ALLOWED


async def test_webhook_ignores_requests_from_outside_the_local_network(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    _set_sources(hass)
    await _setup_p1(hass, monkeypatch, **SOLAR_DATA)
    response = await _request(hass, remote="8.8.8.8")

    # HA's webhook component answers an empty 200 instead of the solar JSON.
    assert response.status == HTTPStatus.OK
    assert response.body is None


async def test_no_webhook_when_disabled(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    _set_sources(hass)
    await _setup_p1(hass, monkeypatch, **{**SOLAR_DATA, CONF_SOLAR_PUSH_ENABLED: False})

    response = await _request(hass)

    # Unregistered webhooks also answer an empty 200 - no JSON body.
    assert response.status == HTTPStatus.OK
    assert response.body is None


async def test_webhook_removed_on_unload(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    _set_sources(hass)
    entry = await _setup_p1(hass, monkeypatch, **SOLAR_DATA)

    assert await hass.config_entries.async_unload(entry.entry_id)
    response = await _request(hass)

    assert response.body is None


async def test_solar_url_sensor_follows_the_setting(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    _set_sources(hass)
    entry = await _setup_p1(hass, monkeypatch, **SOLAR_DATA)
    entity_registry = er.async_get(hass)
    unique_id = f"{entry.entry_id}_solar_push_url"

    entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id is not None
    assert hass.states.get(entity_id).state.endswith(f"/api/webhook/{WEBHOOK_ID}")

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_SOLAR_PUSH_ENABLED: False}
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id) is None


# ---------------------------------------------------------------------------
# Config / options flow
# ---------------------------------------------------------------------------


async def test_own_p1_solar_sensors_are_excluded_from_the_pickers(
    hass, enable_custom_integrations, monkeypatch
) -> None:
    entry = await _setup_p1(hass, monkeypatch)
    entity_registry = er.async_get(hass)

    own = solar_push.own_solar_entity_ids(hass)

    assert sorted(own) == sorted(
        entity_registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}{suffix}")
        for suffix in ("_solarreading_current", "_solarreading_total")
    )


class _FormRecorder:
    """Records async_show_form/async_create_entry instead of HA's flow manager handling them."""

    def __init__(self, hass) -> None:
        self.hass = hass
        self.data: dict = {}
        self.created: dict | None = None
        self.shown: dict | None = None

    def async_create_entry(self, *, title: str, data: dict):
        self.created = {"title": title, "data": data}
        return self.created

    def async_show_form(self, *, step_id: str, data_schema, errors=None, description_placeholders=None):
        self.shown = {
            "step_id": step_id,
            "errors": errors or {},
            "placeholders": description_placeholders,
        }
        return self.shown


class _FakeFlow(_FormRecorder, P1MeterFlowMixin):
    pass


async def test_config_flow_with_solar(hass, monkeypatch) -> None:
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.config_flow._test_connection",
        AsyncMock(return_value=True),
    )
    _set_sources(hass, power="2340", power_unit="W", energy="15234", energy_unit="kWh")
    flow = _FakeFlow(hass)

    await flow.async_step_p1_meter(
        {"host": "http://p1.local", "name": "P1", "scan_interval": 15, CONF_SOLAR_PUSH_ENABLED: True}
    )
    assert flow.shown["step_id"] == "p1_meter_solar"
    assert flow.created is None

    await flow.async_step_p1_meter_solar(
        {CONF_SOLAR_POWER_ENTITY: POWER, CONF_SOLAR_ENERGY_ENTITY: ENERGY}
    )
    assert flow.shown["step_id"] == "p1_meter_solar_url"
    webhook_id = flow._p1_entry_data[CONF_SOLAR_WEBHOOK_ID]
    assert flow.shown["placeholders"]["url"].endswith(f"/api/webhook/{webhook_id}")
    assert flow.shown["placeholders"]["preview"] == '{"current": 2340, "total": 15234000}'

    await flow.async_step_p1_meter_solar_url({})
    assert flow.created["data"][CONF_SOLAR_PUSH_ENABLED] is True
    assert flow.created["data"][CONF_SOLAR_POWER_ENTITY] == POWER
    assert flow.created["data"][CONF_SOLAR_ENERGY_ENTITY] == ENERGY
    assert flow.created["data"][CONF_SOLAR_WEBHOOK_ID] == webhook_id


async def test_config_flow_without_solar_creates_entry_directly(hass, monkeypatch) -> None:
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.config_flow._test_connection",
        AsyncMock(return_value=True),
    )
    flow = _FakeFlow(hass)

    await flow.async_step_p1_meter({"host": "http://p1.local", "name": "P1", "scan_interval": 15})

    assert flow.created["data"][CONF_SOLAR_PUSH_ENABLED] is False


async def test_solar_step_rejects_wrong_units(hass) -> None:
    hass.states.async_set(POWER, "1", {"unit_of_measurement": "kWh"})
    hass.states.async_set(ENERGY, "1", {"unit_of_measurement": "W"})
    flow = _FakeFlow(hass)
    flow._p1_entry_data = {"name": "P1"}

    await flow.async_step_p1_meter_solar(
        {CONF_SOLAR_POWER_ENTITY: POWER, CONF_SOLAR_ENERGY_ENTITY: ENERGY}
    )

    assert flow.shown["errors"] == {
        CONF_SOLAR_POWER_ENTITY: "invalid_power_unit",
        CONF_SOLAR_ENERGY_ENTITY: "invalid_energy_unit",
    }


class _FakeOptionsFlow(_FormRecorder, P1MeterOptionsFlow):
    def __init__(self, hass, config_entry) -> None:
        super().__init__(hass)
        self._config_entry = config_entry
        self.updated: dict | None = None
        self.reloaded = False

        def _update(_entry, *, data):
            self.updated = data

        async def _reload(_entry_id):
            self.reloaded = True

        self.hass = SimpleNamespace(
            states=hass.states,
            data=hass.data,
            config=hass.config,
            config_entries=SimpleNamespace(async_update_entry=_update, async_reload=_reload),
        )

    @property
    def config_entry(self):
        return self._config_entry


async def test_options_flow_keeps_the_webhook_id(hass, monkeypatch) -> None:
    """Re-running the options flow must not change the URL already entered in the P1."""
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.config_flow._test_connection",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.solar_push.own_solar_entity_ids",
        lambda _hass: [],
    )
    _set_sources(hass)
    entry = SimpleNamespace(
        entry_id="p1_entry",
        data={"host": "http://p1.local", "scan_interval": 15, **SOLAR_DATA},
    )
    flow = _FakeOptionsFlow(hass, entry)

    await flow.async_step_p1_meter_init(
        {"host": "http://p1.local", "scan_interval": 15, CONF_SOLAR_PUSH_ENABLED: True}
    )
    assert flow.shown["step_id"] == "p1_meter_solar"
    await flow.async_step_p1_meter_solar(
        {CONF_SOLAR_POWER_ENTITY: POWER, CONF_SOLAR_ENERGY_ENTITY: ENERGY}
    )
    await flow.async_step_p1_meter_solar_url({})

    assert flow.updated[CONF_SOLAR_WEBHOOK_ID] == WEBHOOK_ID
    assert flow.reloaded is True


async def test_options_flow_turning_solar_off_saves_directly(hass, monkeypatch) -> None:
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.p1_meter.config_flow._test_connection",
        AsyncMock(return_value=True),
    )
    entry = SimpleNamespace(
        entry_id="p1_entry",
        data={"host": "http://p1.local", "scan_interval": 15, **SOLAR_DATA},
    )
    flow = _FakeOptionsFlow(hass, entry)

    await flow.async_step_p1_meter_init(
        {"host": "http://p1.local", "scan_interval": 15, CONF_SOLAR_PUSH_ENABLED: False}
    )

    assert flow.updated[CONF_SOLAR_PUSH_ENABLED] is False
    # Kept, so turning it back on gives the same URL as before.
    assert flow.updated[CONF_SOLAR_WEBHOOK_ID] == WEBHOOK_ID
    assert flow.reloaded is True
