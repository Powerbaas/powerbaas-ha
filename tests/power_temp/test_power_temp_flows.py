"""Repair flow (adopt a new sensor) and options flow (manage configured sensors)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.powerbaas.const import DOMAIN
from custom_components.powerbaas.devices.power_temp.client import PowerTempCommandError
from custom_components.powerbaas.devices.power_temp.config_flow import PowerTempOptionsFlow
from custom_components.powerbaas.devices.power_temp.repairs import PowerTempNewSensorRepairFlow
from custom_components.powerbaas.repairs import async_create_fix_flow


def _coordinator():
    configured = {"port": 1, "name": "Groep 1", "offsetC": 0.5, "enabled": True, "ambient": False}
    return SimpleNamespace(
        device_name="PowerTemp",
        data={
            "config": {"sensors": [configured]},
            "ports": {
                1: {"port": 1, "name": "Groep 1", "present": True, "configured": True},
                5: {"port": 5, "name": "", "type": "ntc", "celsius": 30.1, "present": True, "configured": False},
            },
        },
        configured_sensor=lambda port: configured if port == 1 else None,
        async_save_sensor=AsyncMock(),
        async_remove_sensor=AsyncMock(),
    )


def _hass(coordinator=None):
    entries = {"pt_entry": {"coordinator": coordinator}} if coordinator else {}
    return SimpleNamespace(data={DOMAIN: entries})


def _prepare(flow, hass):
    flow.hass = hass
    flow.flow_id = "flow"
    flow.handler = DOMAIN
    return flow


async def test_fix_flow_routes_new_sensor_issue() -> None:
    flow = await async_create_fix_flow(
        None, "power_temp_new_sensor_pt_entry_5", {"entry_id": "pt_entry", "port": 5}
    )

    assert isinstance(flow, PowerTempNewSensorRepairFlow)
    assert flow._port == 5


async def test_repair_flow_shows_detected_sensor() -> None:
    coordinator = _coordinator()
    flow = _prepare(PowerTempNewSensorRepairFlow("pt_entry", 5), _hass(coordinator))

    # The repairs flow manager opens the flow with the issue_id as init-step input.
    result = await flow.async_step_init({"issue_id": "power_temp_new_sensor_pt_entry_5"})

    assert result["type"] == "form"
    assert result["step_id"] == "adopt"
    coordinator.async_save_sensor.assert_not_awaited()
    assert result["description_placeholders"]["sensor_type"] == "ntc"
    assert result["description_placeholders"]["temperature"] == "30.1 °C"


async def test_repair_flow_adopts_sensor() -> None:
    coordinator = _coordinator()
    flow = _prepare(PowerTempNewSensorRepairFlow("pt_entry", 5), _hass(coordinator))

    result = await flow.async_step_adopt({"name": " Groep 5 ", "offset_c": -0.2})

    assert result["type"] == "create_entry"
    coordinator.async_save_sensor.assert_awaited_once_with(5, name="Groep 5", offset_c=-0.2, enabled=True)


async def test_repair_flow_rejects_too_long_name() -> None:
    coordinator = _coordinator()
    flow = _prepare(PowerTempNewSensorRepairFlow("pt_entry", 5), _hass(coordinator))

    result = await flow.async_step_adopt({"name": "x" * 32, "offset_c": 0})

    assert result["errors"] == {"name": "name_too_long"}
    coordinator.async_save_sensor.assert_not_awaited()


async def test_repair_flow_reports_device_rejection() -> None:
    coordinator = _coordinator()
    coordinator.async_save_sensor.side_effect = PowerTempCommandError("too_many_sensors")
    flow = _prepare(PowerTempNewSensorRepairFlow("pt_entry", 5), _hass(coordinator))

    result = await flow.async_step_adopt({"name": "Groep 5", "offset_c": 0})

    assert result["errors"] == {"base": "cannot_save"}


async def test_repair_flow_aborts_when_entry_not_loaded() -> None:
    flow = _prepare(PowerTempNewSensorRepairFlow("pt_entry", 5), _hass())

    result = await flow.async_step_init({"issue_id": "power_temp_new_sensor_pt_entry_5"})

    assert result["type"] == "abort"
    assert result["reason"] == "device_unavailable"


def _options_flow(coordinator):
    flow = PowerTempOptionsFlow(SimpleNamespace(entry_id="pt_entry", options={}, data={}))
    return _prepare(flow, _hass(coordinator))


async def test_options_init_is_a_menu() -> None:
    result = await _options_flow(_coordinator()).async_step_init()

    assert result["type"] == "menu"
    assert result["menu_options"] == ["power_temp_device_config", "power_temp_sensors"]


async def test_options_lists_only_configured_sensors() -> None:
    result = await _options_flow(_coordinator()).async_step_power_temp_sensors()

    port_validator = result["data_schema"].schema
    choices = next(iter(port_validator.values())).container
    assert choices == {"1": "Groep 1 (port 1)"}


async def test_options_edit_sensor() -> None:
    coordinator = _coordinator()
    flow = _options_flow(coordinator)
    await flow.async_step_power_temp_sensors({"port": "1"})

    result = await flow.async_step_power_temp_sensor(
        {"name": "Wasmachine", "offset_c": 1.0, "enabled": False, "remove": False}
    )

    assert result["type"] == "create_entry"
    coordinator.async_save_sensor.assert_awaited_once_with(1, name="Wasmachine", offset_c=1.0, enabled=False)


async def test_options_remove_sensor() -> None:
    coordinator = _coordinator()
    flow = _options_flow(coordinator)
    await flow.async_step_power_temp_sensors({"port": "1"})

    result = await flow.async_step_power_temp_sensor(
        {"name": "Groep 1", "offset_c": 0.5, "enabled": True, "remove": True}
    )

    assert result["type"] == "create_entry"
    coordinator.async_remove_sensor.assert_awaited_once_with(1)
    coordinator.async_save_sensor.assert_not_awaited()


async def test_options_sensors_abort_when_none_configured() -> None:
    coordinator = _coordinator()
    coordinator.data["config"]["sensors"] = []

    result = await _options_flow(coordinator).async_step_power_temp_sensors()

    assert result["reason"] == "no_sensors"
