"""Battery priority steps in the Boiler Controller config and options flows."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.powerbaas.devices.boiler_controller.config_flow import (
    BoilerControllerFlowMixin,
    BoilerControllerOptionsFlow,
)
from custom_components.powerbaas.devices.boiler_controller.const import (
    BATTERY_SENSOR_TYPE_NET,
    BATTERY_SENSOR_TYPE_NONE,
    BATTERY_SENSOR_TYPE_SPLIT,
    CONF_BATTERY_CHARGE_NEGATIVE,
    CONF_BATTERY_CHARGE_SENSOR,
    CONF_BATTERY_DISCHARGE_SENSOR,
    CONF_BATTERY_FULL_SOC,
    CONF_BATTERY_MAX_CHARGE_WATTS,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SENSOR_TYPE,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_TAPER_SOC,
    CONF_BATTERY_TAPER_WATTS,
    CONF_POWER_SENSOR,
    CONF_SAFETY_MARGIN_WATTS,
)

NET_SENSOR = "sensor.net_power"


def _priority_input(battery_type: str) -> dict:
    return {CONF_BATTERY_SENSOR_TYPE: battery_type, CONF_SAFETY_MARGIN_WATTS: 50.0}


def _battery_settings(**extra) -> dict:
    return {CONF_BATTERY_FULL_SOC: 99.0, CONF_BATTERY_MAX_CHARGE_WATTS: 800.0, **extra}


class _FakeFlow(BoilerControllerFlowMixin):
    def __init__(self, hass) -> None:
        self.hass = hass
        self.data: dict = {"name": "Boiler"}
        self.created: dict | None = None

    def async_show_form(self, *, step_id: str, data_schema, errors=None, **_kwargs):
        return {"step_id": step_id, "errors": errors}

    def async_create_entry(self, *, title: str, data: dict):
        self.created = data
        return {"type": "create_entry"}


async def test_config_flow_power_sensor_leads_to_battery_step(hass) -> None:
    hass.states.async_set(NET_SENSOR, "-300", {"unit_of_measurement": "W"})
    flow = _FakeFlow(hass)

    result = await flow.async_step_power_sensor_net({CONF_POWER_SENSOR: NET_SENSOR})

    assert result["step_id"] == "battery_priority"


async def test_config_flow_without_battery_stores_only_margin(hass) -> None:
    flow = _FakeFlow(hass)

    await flow.async_step_battery_priority(_priority_input(BATTERY_SENSOR_TYPE_NONE))

    assert flow.created[CONF_BATTERY_SENSOR_TYPE] == BATTERY_SENSOR_TYPE_NONE
    assert flow.created[CONF_SAFETY_MARGIN_WATTS] == 50
    assert CONF_BATTERY_POWER_SENSOR not in flow.created
    assert CONF_BATTERY_SOC_SENSOR not in flow.created
    assert CONF_BATTERY_MAX_CHARGE_WATTS not in flow.created


async def test_config_flow_net_battery(hass) -> None:
    flow = _FakeFlow(hass)

    result = await flow.async_step_battery_priority(_priority_input(BATTERY_SENSOR_TYPE_NET))
    assert result["step_id"] == "battery_sensor_net"

    await flow.async_step_battery_sensor_net(
        _battery_settings(**{
            CONF_BATTERY_POWER_SENSOR: "sensor.battery",
            CONF_BATTERY_CHARGE_NEGATIVE: True,
            CONF_BATTERY_SOC_SENSOR: "sensor.soc",
        })
    )

    assert flow.created[CONF_BATTERY_POWER_SENSOR] == "sensor.battery"
    assert flow.created[CONF_BATTERY_CHARGE_NEGATIVE] is True
    assert flow.created[CONF_BATTERY_SOC_SENSOR] == "sensor.soc"
    assert flow.created[CONF_BATTERY_MAX_CHARGE_WATTS] == 800
    assert CONF_BATTERY_CHARGE_SENSOR not in flow.created


async def test_config_flow_split_battery_rejects_same_sensor(hass) -> None:
    flow = _FakeFlow(hass)
    await flow.async_step_battery_priority(_priority_input(BATTERY_SENSOR_TYPE_SPLIT))

    result = await flow.async_step_battery_sensor_split(
        _battery_settings(**{
            CONF_BATTERY_CHARGE_SENSOR: "sensor.a",
            CONF_BATTERY_DISCHARGE_SENSOR: "sensor.a",
        })
    )

    assert result["errors"] == {CONF_BATTERY_DISCHARGE_SENSOR: "sensors_must_differ"}
    assert flow.created is None


async def test_options_flow_switching_split_to_net_clears_split_sensors(hass) -> None:
    entry = SimpleNamespace(
        entry_id="entry1",
        unique_id="pb-bc-1",
        options={},
        data={
            CONF_POWER_SENSOR: NET_SENSOR,
            CONF_BATTERY_SENSOR_TYPE: BATTERY_SENSOR_TYPE_SPLIT,
            CONF_BATTERY_CHARGE_SENSOR: "sensor.charge",
            CONF_BATTERY_DISCHARGE_SENSOR: "sensor.discharge",
            CONF_BATTERY_SOC_SENSOR: "sensor.soc",
        },
    )
    flow = BoilerControllerOptionsFlow(entry)
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=MagicMock(), async_reload=AsyncMock())
    )
    flow.async_show_form = lambda **kwargs: {"step_id": kwargs["step_id"]}
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry"}

    await flow.async_step_battery_priority(_priority_input(BATTERY_SENSOR_TYPE_NET))
    await flow.async_step_battery_sensor_net(
        _battery_settings(**{
            CONF_BATTERY_POWER_SENSOR: "sensor.battery",
            CONF_BATTERY_CHARGE_NEGATIVE: False,
        })
    )

    new_data = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert new_data[CONF_BATTERY_SENSOR_TYPE] == BATTERY_SENSOR_TYPE_NET
    assert new_data[CONF_BATTERY_POWER_SENSOR] == "sensor.battery"
    assert CONF_BATTERY_CHARGE_SENSOR not in new_data
    assert CONF_BATTERY_DISCHARGE_SENSOR not in new_data
    # Left empty in the form -> SoC sensor removed.
    assert CONF_BATTERY_SOC_SENSOR not in new_data
    assert new_data[CONF_POWER_SENSOR] == NET_SENSOR


async def test_battery_forms_render(hass) -> None:
    flow = _FakeFlow(hass)
    flow.data[CONF_BATTERY_SOC_SENSOR] = "sensor.soc"

    assert (await flow.async_step_battery_priority())["step_id"] == "battery_priority"
    assert (await flow.async_step_battery_sensor_net())["step_id"] == "battery_sensor_net"
    assert (await flow.async_step_battery_sensor_split())["step_id"] == "battery_sensor_split"


async def test_options_flow_switching_to_no_battery_clears_battery_settings(hass) -> None:
    entry = SimpleNamespace(
        entry_id="entry1",
        unique_id="pb-bc-1",
        options={},
        data={
            CONF_POWER_SENSOR: NET_SENSOR,
            CONF_BATTERY_SENSOR_TYPE: BATTERY_SENSOR_TYPE_NET,
            CONF_BATTERY_POWER_SENSOR: "sensor.battery",
            CONF_BATTERY_SOC_SENSOR: "sensor.soc",
            CONF_BATTERY_MAX_CHARGE_WATTS: 800,
        },
    )
    flow = BoilerControllerOptionsFlow(entry)
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=MagicMock(), async_reload=AsyncMock())
    )
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry"}

    await flow.async_step_battery_priority(_priority_input(BATTERY_SENSOR_TYPE_NONE))

    new_data = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert new_data[CONF_BATTERY_SENSOR_TYPE] == BATTERY_SENSOR_TYPE_NONE
    assert new_data[CONF_SAFETY_MARGIN_WATTS] == 50
    for key in (CONF_BATTERY_POWER_SENSOR, CONF_BATTERY_SOC_SENSOR, CONF_BATTERY_MAX_CHARGE_WATTS):
        assert key not in new_data


def _net_input(**extra) -> dict:
    return _battery_settings(**{
        CONF_BATTERY_POWER_SENSOR: "sensor.battery",
        CONF_BATTERY_CHARGE_NEGATIVE: False,
        CONF_BATTERY_SOC_SENSOR: "sensor.soc",
        **extra,
    })


async def test_config_flow_stores_battery_taper(hass) -> None:
    flow = _FakeFlow(hass)
    await flow.async_step_battery_priority(_priority_input(BATTERY_SENSOR_TYPE_NET))

    await flow.async_step_battery_sensor_net(
        _net_input(**{CONF_BATTERY_TAPER_SOC: 95.0, CONF_BATTERY_TAPER_WATTS: 500.0})
    )

    assert flow.created[CONF_BATTERY_TAPER_SOC] == 95
    assert flow.created[CONF_BATTERY_TAPER_WATTS] == 500


async def test_config_flow_battery_taper_left_empty(hass) -> None:
    flow = _FakeFlow(hass)
    await flow.async_step_battery_priority(_priority_input(BATTERY_SENSOR_TYPE_NET))

    await flow.async_step_battery_sensor_net(_net_input())

    assert CONF_BATTERY_TAPER_SOC not in flow.created
    assert CONF_BATTERY_TAPER_WATTS not in flow.created


@pytest.mark.parametrize(
    ("extra", "errors"),
    [
        ({CONF_BATTERY_TAPER_SOC: 95.0}, {CONF_BATTERY_TAPER_WATTS: "taper_incomplete"}),
        ({CONF_BATTERY_TAPER_WATTS: 500.0}, {CONF_BATTERY_TAPER_SOC: "taper_incomplete"}),
        (
            {CONF_BATTERY_TAPER_SOC: 99.0, CONF_BATTERY_TAPER_WATTS: 500.0},
            {CONF_BATTERY_TAPER_SOC: "taper_not_below_full"},
        ),
        (
            {CONF_BATTERY_SOC_SENSOR: None, CONF_BATTERY_TAPER_SOC: 95.0, CONF_BATTERY_TAPER_WATTS: 500.0},
            {CONF_BATTERY_TAPER_SOC: "taper_needs_soc_sensor"},
        ),
    ],
)
async def test_battery_taper_validation(hass, extra: dict, errors: dict) -> None:
    flow = _FakeFlow(hass)
    await flow.async_step_battery_priority(_priority_input(BATTERY_SENSOR_TYPE_SPLIT))

    result = await flow.async_step_battery_sensor_split(
        _battery_settings(**{
            CONF_BATTERY_CHARGE_SENSOR: "sensor.charge",
            CONF_BATTERY_DISCHARGE_SENSOR: "sensor.discharge",
            CONF_BATTERY_SOC_SENSOR: "sensor.soc",
            **extra,
        })
    )

    assert result["errors"] == errors
    assert flow.created is None


async def test_options_flow_switching_to_no_battery_clears_taper(hass) -> None:
    entry = SimpleNamespace(
        entry_id="entry1",
        unique_id="pb-bc-1",
        options={},
        data={
            CONF_POWER_SENSOR: NET_SENSOR,
            CONF_BATTERY_SENSOR_TYPE: BATTERY_SENSOR_TYPE_NET,
            CONF_BATTERY_POWER_SENSOR: "sensor.battery",
            CONF_BATTERY_TAPER_SOC: 95,
            CONF_BATTERY_TAPER_WATTS: 500,
        },
    )
    flow = BoilerControllerOptionsFlow(entry)
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=MagicMock(), async_reload=AsyncMock())
    )
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry"}

    await flow.async_step_battery_priority(_priority_input(BATTERY_SENSOR_TYPE_NONE))

    new_data = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert CONF_BATTERY_TAPER_SOC not in new_data
    assert CONF_BATTERY_TAPER_WATTS not in new_data
