"""Repairs platform entry point - routes fixable issues to the device-specific flow."""
from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant

from .devices.power_temp.const import NEW_SENSOR_ISSUE_PREFIX
from .devices.power_temp.repairs import PowerTempNewSensorRepairFlow


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    if issue_id.startswith(NEW_SENSOR_ISSUE_PREFIX) and data:
        return PowerTempNewSensorRepairFlow(data["entry_id"], int(data["port"]))
    return ConfirmRepairFlow()
