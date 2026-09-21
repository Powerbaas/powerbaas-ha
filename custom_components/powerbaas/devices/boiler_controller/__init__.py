import logging
import time

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv, issue_registry
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.loader import async_get_integration

from ...const import DOMAIN
from .const import (
    SERVICE_RUN_CALIBRATION,
    SERVICE_CANCEL_CALIBRATION,
    ATTR_CONFIG_ENTRY_ID,
)
from .coordinator import BoilerControllerCoordinator

_LOGGER = logging.getLogger(__name__)

ENTRY_ID_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)
RUN_CALIBRATION_SCHEMA = ENTRY_ID_SCHEMA
CANCEL_CALIBRATION_SCHEMA = ENTRY_ID_SCHEMA


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Set up a Boiler Controller device and return its runtime data."""
    _LOGGER.info("Setting up Boiler Controller")

    try:
        integration = await async_get_integration(hass, DOMAIN)
        integration_version = str(integration.version) if integration.version else "unknown"
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.warning("Could not get integration version from manifest: %s", err)
        integration_version = "unknown"

    coordinator = BoilerControllerCoordinator(hass, entry, integration_version)

    # Gate setup on the device being reachable right now, so an offline
    # device shows up as "Failed setup, will retry" on the Integrations page
    # (HA automatically retries with backoff) instead of silently succeeding.
    if not await coordinator.device_client.async_test_connection():
        raise ConfigEntryNotReady(
            f"Device communication error occurred for {entry.title}"
        )

    await coordinator._async_validate_configuration()
    await coordinator.async_config_entry_first_refresh()

    entry.async_on_unload(
        async_track_state_change_event(
            hass,
            coordinator._tracked_entities,
            coordinator._async_power_sensor_changed,
        )
    )
    entry.async_on_unload(
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, coordinator.async_persist_target_watts_on_stop
        )
    )
    _LOGGER.info(
        "Started listening to power sensor state changes (type=%s) for: %s",
        coordinator.power_sensor_type,
        coordinator._tracked_entities,
    )

    # Run initial update (will fail gracefully if entities don't exist yet)
    await coordinator._async_update()

    await _async_register_services(hass)

    _LOGGER.info("Boiler Controller setup completed")
    return {"coordinator": coordinator}


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clear any open offline issue, and deregister services if no BC entries remain."""
    _LOGGER.info("Unloading Boiler Controller")

    issue_registry.async_delete_issue(
        hass, DOMAIN, f"boiler_controller_offline_{entry.entry_id}"
    )

    domain_data = hass.data.get(DOMAIN, {})
    remaining_coordinators = [
        value
        for key, value in domain_data.items()
        if key != entry.entry_id
        and isinstance(value, dict)
        and isinstance(value.get("coordinator"), BoilerControllerCoordinator)
    ]

    if not remaining_coordinators:
        if hass.services.has_service(DOMAIN, SERVICE_RUN_CALIBRATION):
            hass.services.async_remove(DOMAIN, SERVICE_RUN_CALIBRATION)
        if hass.services.has_service(DOMAIN, SERVICE_CANCEL_CALIBRATION):
            hass.services.async_remove(DOMAIN, SERVICE_CANCEL_CALIBRATION)
        domain_data.pop("_services_registered", None)


def _async_notify_calibration(
    hass: HomeAssistant, entry_id: str, message: str, *, unique: bool = False
) -> None:
    """Post a persistent notification about a calibration run.

    Mirrors what the (now removed) Calibrate Start/Stop buttons used to show
    directly in the UI - kept here so triggering calibration via the service
    (Developer Tools > Actions, a script, or a blueprint) still surfaces the
    same cooldown/duration warning and success/failure feedback.
    """
    suffix = f"_{int(time.time())}" if unique else ""
    persistent_notification.async_create(
        hass,
        message,
        title="Boiler Controller",
        notification_id=f"boiler_controller_calibration_{entry_id}{suffix}",
    )


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register the calibration service once per Home Assistant instance."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_services_registered"):
        return

    async def _handle_run_calibration(call: ServiceCall) -> None:
        coordinator = _async_resolve_coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        entry_id = coordinator.config_entry.entry_id

        _async_notify_calibration(
            hass,
            entry_id,
            "Calibration started.\n\n"
            "- Make sure the boiler is **cooled down** - if it is already at "
            "temperature the heating element cannot reach the higher setpoints "
            "and the curve will be incomplete.\n"
            "- The sweep takes **at least 6 minutes** while it measures every "
            "percentage point against the actual wattage.\n"
            "- Running this manually is **optional** - the controller "
            "calibrates itself automatically over time. Use this action only "
            "when you want an immediate, complete curve.\n\n"
            "Call `powerbaas.bc_cancel_calibration` to abort.",
            unique=True,
        )

        _LOGGER.info("Starting calibration for entry %s", entry_id)
        try:
            await coordinator.async_run_calibration()
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Calibration failed for %s: %s", coordinator.config_entry.title, err)
            _async_notify_calibration(hass, entry_id, f"Calibration failed: {err}")
            raise
        _LOGGER.info("Calibration completed for entry %s", entry_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_RUN_CALIBRATION,
        _handle_run_calibration,
        schema=RUN_CALIBRATION_SCHEMA,
    )

    async def _handle_cancel_calibration(call: ServiceCall) -> None:
        coordinator = _async_resolve_coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))

        requested = await coordinator.async_request_calibration_cancel()
        if not requested:
            raise HomeAssistantError("No calibration run is currently active")

        _LOGGER.info(
            "Calibration cancellation requested for entry %s",
            coordinator.config_entry.entry_id,
        )
        _async_notify_calibration(
            hass,
            coordinator.config_entry.entry_id,
            "Calibration cancellation requested. The sweep will stop after the current step.",
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CANCEL_CALIBRATION,
        _handle_cancel_calibration,
        schema=CANCEL_CALIBRATION_SCHEMA,
    )
    domain_data["_services_registered"] = True


def _async_resolve_coordinator(
    hass: HomeAssistant, entry_id: str | None
) -> BoilerControllerCoordinator:
    coordinators = {
        key: value["coordinator"]
        for key, value in hass.data.get(DOMAIN, {}).items()
        if isinstance(value, dict) and isinstance(value.get("coordinator"), BoilerControllerCoordinator)
    }

    if not coordinators:
        raise HomeAssistantError("No Boiler Controller entries loaded")

    if entry_id:
        coordinator = coordinators.get(entry_id)
        if not coordinator:
            raise HomeAssistantError(f"No Boiler Controller entry with id {entry_id}")
        return coordinator

    if len(coordinators) == 1:
        return next(iter(coordinators.values()))

    raise HomeAssistantError("config_entry_id is required when multiple Boiler Controller entries exist")
