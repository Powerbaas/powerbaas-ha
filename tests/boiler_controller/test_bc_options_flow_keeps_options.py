"""Saving the options flow must not wipe the entry's runtime options.

Home Assistant replaces entry.options with whatever the options flow's
create_entry returns. The BC keeps control mode, max/min heating watts and
target watts in options, so finishing with data={} silently reset Control
Mode to Off on the next restart/reload.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.powerbaas.devices.boiler_controller.config_flow import (
    BoilerControllerOptionsFlow,
)
from custom_components.powerbaas.devices.boiler_controller.const import (
    BATTERY_SENSOR_TYPE_NONE,
    CONF_BATTERY_SENSOR_TYPE,
    CONF_POWER_SENSOR,
    CONF_SAFETY_MARGIN_WATTS,
)

OPTIONS = {"control_mode": "auto", "max_heating_watts": 3000, "min_heating_watts": 100}


async def test_options_flow_returns_existing_options() -> None:
    entry = SimpleNamespace(
        entry_id="entry1",
        unique_id="pb-bc-1",
        options=dict(OPTIONS),
        data={CONF_POWER_SENSOR: "sensor.net_power"},
    )
    flow = BoilerControllerOptionsFlow(entry)
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=MagicMock(), async_reload=AsyncMock())
    )
    flow.async_create_entry = lambda **kwargs: kwargs

    result = await flow.async_step_battery_priority(
        {CONF_BATTERY_SENSOR_TYPE: BATTERY_SENSOR_TYPE_NONE, CONF_SAFETY_MARGIN_WATTS: 0}
    )

    assert result["data"] == OPTIONS
