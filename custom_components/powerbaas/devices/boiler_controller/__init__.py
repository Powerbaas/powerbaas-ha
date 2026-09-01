import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
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


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register the calibration service once per Home Assistant instance."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_services_registered"):
        return

    async def _handle_run_calibration(call: ServiceCall) -> None:
        coordinator = _async_resolve_coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        _LOGGER.info("Starting calibration for entry %s", coordinator.config_entry.entry_id)
        await coordinator.async_run_calibration()
        _LOGGER.info("Calibration completed for entry %s", coordinator.config_entry.entry_id)

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
