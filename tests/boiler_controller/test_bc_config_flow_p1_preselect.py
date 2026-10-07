"""The Boiler Controller flows prefer a configured Powerbaas P1 Meter as power source."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerbaas.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_P1_METER,
    DOMAIN,
)
from custom_components.powerbaas.devices.boiler_controller.config_flow import (
    BoilerControllerFlowMixin,
    BoilerControllerOptionsFlow,
    _find_powerbaas_p1_power_sensor,
)
from custom_components.powerbaas.devices.boiler_controller.const import (
    CONF_POWER_SENSOR,
    CONF_POWER_SENSOR_TYPE,
    CONF_RETURN_SENSOR,
    CONF_USAGE_SENSOR,
    POWER_SENSOR_TYPE_SPLIT,
)
from custom_components.powerbaas.devices.p1_meter.const import (
    P1_POWER_USAGE_UNIQUE_ID_SUFFIX,
)

OTHER_SENSOR = "sensor.other_brand_net_power"


class _FakeFlow(BoilerControllerFlowMixin):
    """Minimal harness exposing only what the power sensor steps touch."""

    def __init__(self, hass) -> None:
        self.hass = hass
        self.data: dict = {}
        self.shown: dict | None = None

    def async_show_form(self, *, step_id: str, data_schema, errors=None, **_kwargs):
        self.shown = {"step_id": step_id, "data_schema": data_schema}
        return self.shown


def _add_p1(hass, *, disabled: bool = False) -> str:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DEVICE_TYPE: DEVICE_TYPE_P1_METER})
    entry.add_to_hass(hass)
    reg_entry = er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}{P1_POWER_USAGE_UNIQUE_ID_SUFFIX}",
        suggested_object_id="powerbaas_power_usage",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.USER if disabled else None,
    )
    if not disabled:
        hass.states.async_set(
            reg_entry.entity_id, "-1200", {"unit_of_measurement": "W", "friendly_name": "Power Usage"}
        )
    return reg_entry.entity_id


def _schema_default(form: dict, key: str):
    for marker in form["data_schema"].schema:
        if marker == key:
            default = marker.default
            return default() if callable(default) else None
    raise KeyError(key)


def _dropdown_values(form: dict, key: str) -> list[str]:
    for marker, value in form["data_schema"].schema.items():
        if marker == key:
            return [opt["value"] for opt in value.config["options"]]
    raise KeyError(key)


async def test_finds_p1_power_usage_sensor(hass) -> None:
    p1_sensor = _add_p1(hass)

    assert _find_powerbaas_p1_power_sensor(hass) == p1_sensor


async def test_ignores_disabled_p1_sensor(hass) -> None:
    _add_p1(hass, disabled=True)

    assert _find_powerbaas_p1_power_sensor(hass) is None


async def test_config_flow_preselects_p1_and_lists_it_first(hass) -> None:
    hass.states.async_set(OTHER_SENSOR, "300", {"unit_of_measurement": "W"})
    p1_sensor = _add_p1(hass)
    flow = _FakeFlow(hass)

    form = await flow.async_step_power_sensor_net()

    assert _schema_default(form, CONF_POWER_SENSOR) == p1_sensor
    assert _dropdown_values(form, CONF_POWER_SENSOR) == [p1_sensor, OTHER_SENSOR]


async def test_config_flow_without_p1_has_no_default(hass) -> None:
    hass.states.async_set(OTHER_SENSOR, "300", {"unit_of_measurement": "W"})
    flow = _FakeFlow(hass)

    form = await flow.async_step_power_sensor_net()

    assert _schema_default(form, CONF_POWER_SENSOR) is None
    assert _dropdown_values(form, CONF_POWER_SENSOR) == [OTHER_SENSOR]


def _options_flow(hass, data: dict) -> BoilerControllerOptionsFlow:
    flow = BoilerControllerOptionsFlow(SimpleNamespace(data=data))
    flow.hass = hass
    flow.shown = None

    def _show(*, step_id, data_schema, errors=None, **_kwargs):
        flow.shown = {"step_id": step_id, "data_schema": data_schema}
        return flow.shown

    flow.async_show_form = _show
    return flow


async def test_options_flow_keeps_current_sensor_over_p1(hass) -> None:
    hass.states.async_set(OTHER_SENSOR, "300", {"unit_of_measurement": "W"})
    _add_p1(hass)
    flow = _options_flow(hass, {CONF_POWER_SENSOR: OTHER_SENSOR})

    form = await flow.async_step_power_sensor_net()

    assert _schema_default(form, CONF_POWER_SENSOR) == OTHER_SENSOR


async def test_options_flow_switching_from_split_preselects_p1(hass) -> None:
    hass.states.async_set(OTHER_SENSOR, "300", {"unit_of_measurement": "W"})
    p1_sensor = _add_p1(hass)
    flow = _options_flow(
        hass,
        {
            CONF_POWER_SENSOR_TYPE: POWER_SENSOR_TYPE_SPLIT,
            CONF_RETURN_SENSOR: "sensor.a",
            CONF_USAGE_SENSOR: "sensor.b",
        },
    )

    form = await flow.async_step_power_sensor_net()

    assert _schema_default(form, CONF_POWER_SENSOR) == p1_sensor
