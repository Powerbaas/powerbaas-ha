"""Button entities for the Boiler Controller integration."""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _device_info(coordinator, config_entry: ConfigEntry) -> dict[str, Any]:
    system = (coordinator.data or {}).get("system") or {}
    return {
        "identifiers": {(DOMAIN, config_entry.entry_id)},
        "name": config_entry.title,
        "manufacturer": "Powerbaas",
        "model": "Boiler Controller",
        "sw_version": str(system.get("firmwareVersion", "Unknown")),
    }


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    async_add_entities(
        [
            BoilerCalibrationButton(coordinator, config_entry),
            BoilerCalibrationStopButton(coordinator, config_entry),
        ],
        True,
    )


class _BaseCalibrationButton(CoordinatorEntity, ButtonEntity):
    """Shared behavior for calibration buttons."""

    _attr_should_poll = False

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry

    @property
    def device_info(self) -> dict[str, Any]:
        return _device_info(self.coordinator, self.config_entry)

    async def _async_notify(self, message: str, *, unique: bool = False) -> None:
        suffix = f"_{int(time.time())}" if unique else ""
        notification_id = (
            f"boiler_controller_calibration_{self.config_entry.entry_id}{suffix}"
        )
        _LOGGER.info(
            "Posting persistent notification %s for %s",
            notification_id,
            self.config_entry.title,
        )
        persistent_notification.async_create(
            self.hass,
            message,
            title="Boiler Controller",
            notification_id=notification_id,
        )


class BoilerCalibrationButton(_BaseCalibrationButton):
    """Button that triggers a calibration run on the BC module's heating dimmer."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator, config_entry)
        self._attr_name = "Calibrate Start"
        self._attr_unique_id = f"{config_entry.entry_id}_calibrate_device"
        self._attr_icon = "mdi:chart-bell-curve"

    async def async_press(self) -> None:
        if (self.coordinator.data or {}).get("calibration_active"):
            message = f"Calibration already active for {self.config_entry.title}"
            _LOGGER.warning(message)
            raise HomeAssistantError(message)

        _LOGGER.info("Calibration button pressed for %s", self.config_entry.title)

        await self._async_notify(
            "Calibration started.\n\n"
            "- Make sure the boiler is **cooled down** - if it is already at "
            "temperature the heating element cannot reach the higher setpoints "
            "and the curve will be incomplete.\n"
            "- The sweep takes **at least 6 minutes** while it measures every "
            "percentage point against the actual wattage.\n"
            "- Running this manually is **optional** - the controller will "
            "calibrate itself automatically over time. Use this button only when "
            "you want an immediate, complete curve.\n\n"
            "Press *Calibrate Stop* to abort.",
            unique=True,
        )

        async def _run_calibration() -> None:
            try:
                await self.coordinator.async_run_calibration()
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.error("Calibration failed for %s: %s", self.config_entry.title, err)
                await self._async_notify(f"Calibration failed: {err}")

        self.hass.async_create_task(_run_calibration())

    @property
    def available(self) -> bool:
        return not (self.coordinator.data or {}).get("calibration_active")


class BoilerCalibrationStopButton(_BaseCalibrationButton):
    """Button that cancels the ongoing calibration sweep."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator, config_entry)
        self._attr_name = "Calibrate Stop"
        self._attr_unique_id = f"{config_entry.entry_id}_stop_calibration"
        self._attr_icon = "mdi:stop-circle"

    async def async_press(self) -> None:
        if not (self.coordinator.data or {}).get("calibration_active"):
            raise HomeAssistantError("Calibration is not currently running")

        requested = await self.coordinator.async_request_calibration_cancel()
        if not requested:
            raise HomeAssistantError("No calibration run to cancel")

        _LOGGER.info("Calibration cancellation requested via button for %s", self.config_entry.title)
        await self._async_notify(
            "Calibration cancellation requested. The sweep will stop after the current step."
        )

    @property
    def available(self) -> bool:
        return bool((self.coordinator.data or {}).get("calibration_active"))
