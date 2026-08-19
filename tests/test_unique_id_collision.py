"""Regression: adding a second Powerbaas device via the LAN proxy must not
replace the first.

Boiler Controller, Airco Bridge and RGB share one ConfigFlow class. Mixin
methods with the same name resolve via MRO. Boiler Controller's
``_derive_device_id`` strips non-default ports, so two proxy URLs on
``host.docker.internal:18080`` and ``:18082`` both became unique_id
``host.docker.internal``. Home Assistant then unloads the existing entry
and creates the new one in its place.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.powerbaas.const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_AIRCO_BRIDGE,
    DEVICE_TYPE_RGB,
)
from custom_components.powerbaas.devices.airco_bridge.config_flow import AircoBridgeFlowMixin
from custom_components.powerbaas.devices.airco_bridge.const import CONF_DEVICE_URL as AIRCO_URL
from custom_components.powerbaas.devices.boiler_controller.config_flow import (
    BoilerControllerFlowMixin,
)
from custom_components.powerbaas.devices.p1_meter.config_flow import P1MeterFlowMixin
from custom_components.powerbaas.devices.rgb.config_flow import RgbFlowMixin
from custom_components.powerbaas.devices.rgb.const import CONF_DEVICE_URL as RGB_URL


class _CombinedFlow(
    P1MeterFlowMixin,
    BoilerControllerFlowMixin,
    AircoBridgeFlowMixin,
    RgbFlowMixin,
):
    """Same mixin MRO as PowerbaasConfigFlow, without HA's ConfigFlow constructor."""

    def __init__(self) -> None:
        self.data: dict = {}
        self.unique_id = None
        self.created: dict | None = None
        self.shown: dict | None = None
        self.aborted: str | None = None
        self.context: dict = {}
        self.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_entries=lambda _domain: [])
        )

    async def async_set_unique_id(self, unique_id, *, raise_on_progress=True):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self, updates=None, **_kwargs):
        return None

    def async_create_entry(self, *, title: str, data: dict):
        self.created = {"title": title, "data": data}
        return self.created

    def async_show_form(self, *, step_id: str, data_schema, errors: dict, description_placeholders=None):
        self.shown = {"step_id": step_id, "errors": errors}
        return self.shown

    def async_abort(self, *, reason: str):
        self.aborted = reason
        return {"reason": reason}


async def test_rgb_proxy_url_unique_id_includes_port_and_device_type() -> None:
    flow = _CombinedFlow()
    flow.data = {CONF_DEVICE_TYPE: DEVICE_TYPE_RGB, "name": "RGB"}
    flow._test_rgb_connection = AsyncMock(return_value=True)
    flow._async_fetch_rgb_system_hostname = AsyncMock(return_value=None)

    await flow.async_step_rgb_device_config(
        {RGB_URL: "http://host.docker.internal:18082"}
    )

    assert flow.created is not None
    assert flow.created["data"][RGB_URL] == "http://host.docker.internal:18082"
    assert flow.created["data"]["device_id"] == "host.docker.internal:18082"
    assert flow.unique_id == "rgb:host.docker.internal:18082"


async def test_airco_proxy_url_unique_id_includes_port_and_device_type() -> None:
    flow = _CombinedFlow()
    flow.data = {CONF_DEVICE_TYPE: DEVICE_TYPE_AIRCO_BRIDGE, "name": "Airco"}
    flow._test_airco_connection = AsyncMock(return_value=True)
    flow._async_fetch_airco_system_hostname = AsyncMock(return_value=None)

    await flow.async_step_airco_device_config(
        {AIRCO_URL: "http://host.docker.internal:18080"}
    )

    assert flow.created is not None
    assert flow.created["data"][AIRCO_URL] == "http://host.docker.internal:18080"
    assert flow.created["data"]["device_id"] == "host.docker.internal:18080"
    assert flow.unique_id == "airco_bridge:host.docker.internal:18080"


async def test_rgb_and_airco_proxy_unique_ids_do_not_collide() -> None:
    rgb = _CombinedFlow()
    rgb.data = {CONF_DEVICE_TYPE: DEVICE_TYPE_RGB, "name": "RGB"}
    rgb._test_rgb_connection = AsyncMock(return_value=True)
    rgb._async_fetch_rgb_system_hostname = AsyncMock(return_value=None)
    await rgb.async_step_rgb_device_config({RGB_URL: "http://host.docker.internal:18082"})

    airco = _CombinedFlow()
    airco.data = {CONF_DEVICE_TYPE: DEVICE_TYPE_AIRCO_BRIDGE, "name": "Airco"}
    airco._test_airco_connection = AsyncMock(return_value=True)
    airco._async_fetch_airco_system_hostname = AsyncMock(return_value=None)
    await airco.async_step_airco_device_config(
        {AIRCO_URL: "http://host.docker.internal:18080"}
    )

    assert rgb.unique_id != airco.unique_id
