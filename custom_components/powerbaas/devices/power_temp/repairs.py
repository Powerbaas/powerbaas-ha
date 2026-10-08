"""Repair flow for adopting a newly detected PowerTemp sensor."""
from __future__ import annotations

import logging

from homeassistant.components.repairs import RepairsFlow

from .client import PowerTempCommandError
from .config_flow import coordinator_for_entry, sensor_schema, validate_sensor_input

_LOGGER = logging.getLogger(__name__)


class PowerTempNewSensorRepairFlow(RepairsFlow):
    """Name a detected-but-unconfigured sensor and save it to the device config."""

    def __init__(self, entry_id: str, port: int) -> None:
        self._entry_id = entry_id
        self._port = port

    async def async_step_init(self, user_input=None):
        coordinator = coordinator_for_entry(self.hass, self._entry_id)
        if coordinator is None:
            return self.async_abort(reason="device_unavailable")

        errors = {}
        if user_input is not None:
            errors = validate_sensor_input(user_input)
            if not errors:
                try:
                    await coordinator.async_save_sensor(
                        self._port,
                        name=(user_input.get("name") or "").strip(),
                        offset_c=user_input["offset_c"],
                        enabled=True,
                    )
                except PowerTempCommandError as err:
                    _LOGGER.warning("Adopting PowerTemp port %s failed: %s", self._port, err.code)
                    errors["base"] = "cannot_save"
                else:
                    return self.async_create_entry(data={})

        port_data = ((coordinator.data or {}).get("ports") or {}).get(self._port) or {}
        celsius = port_data.get("celsius")
        return self.async_show_form(
            step_id="init",
            data_schema=sensor_schema(
                (user_input or {}).get("name", ""), (user_input or {}).get("offset_c", 0.0)
            ),
            errors=errors,
            description_placeholders={
                "name": coordinator.device_name,
                "port": str(self._port),
                "sensor_type": str(port_data.get("type") or "?"),
                "temperature": f"{celsius} °C" if celsius is not None else "-",
            },
        )
