"""P1 meter device support for the Powerbaas integration."""
import asyncio
import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ...const import DOMAIN, OFFLINE_AFTER_CONSECUTIVE_FAILURES
from .const import DEFAULT_SCAN_INTERVAL, MIN_TIMEOUT, MAX_TIMEOUT, TIMEOUT_RATIO

_LOGGER = logging.getLogger(__name__)

LEGACY_UNIQUE_ID_PREFIX = f"{DOMAIN}_"


def migrate_legacy_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Move entities created before the per-device unique_id scheme.

    Old unique_id: "powerbaas_<path>" (no entry_id -> orphaned once we switched
    to "<entry_id>_<path>" to support multiple devices). Only the unique_id is
    touched, entity_id is left as-is - it may already be customized by the user,
    and there's nothing in the registry that tells us whether it was.
    """
    registry = er.async_get(hass)
    new_prefix = f"{entry.entry_id}_"

    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.platform != DOMAIN:
            continue
        if not reg_entry.unique_id.startswith(LEGACY_UNIQUE_ID_PREFIX):
            continue
        if reg_entry.unique_id.startswith(new_prefix):
            continue

        suffix = reg_entry.unique_id[len(LEGACY_UNIQUE_ID_PREFIX):]
        new_unique_id = f"{new_prefix}{suffix}"

        try:
            registry.async_update_entity(reg_entry.entity_id, new_unique_id=new_unique_id)
        except ValueError as err:
            _LOGGER.error(
                "Failed to migrate Powerbaas entity %s to unique_id=%s: %s",
                reg_entry.entity_id,
                new_unique_id,
                err,
            )
            continue

        _LOGGER.info(
            "Migrated legacy Powerbaas entity %s to unique_id=%s",
            reg_entry.entity_id,
            new_unique_id,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Set up a P1 meter device and return its runtime data."""
    api_url = entry.data.get("host")
    scan_interval = entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL)
    request_timeout = max(MIN_TIMEOUT, min(MAX_TIMEOUT, scan_interval * TIMEOUT_RATIO))

    if not api_url:
        _LOGGER.error("No host address configured for Powerbaas.")
        raise ConfigEntryNotReady("No host address available.")

    device_name = entry.title or "Powerbaas"
    offline_issue_id = f"p1_meter_offline_{entry.entry_id}"
    consecutive_failures = 0

    def _register_fetch_failure() -> None:
        nonlocal consecutive_failures
        consecutive_failures += 1
        if consecutive_failures == OFFLINE_AFTER_CONSECUTIVE_FAILURES:
            coordinator.device_online = False
            _LOGGER.warning(
                "P1 meter offline for %s after %s consecutive failed fetches",
                device_name,
                consecutive_failures,
            )
            issue_registry.async_create_issue(
                hass,
                DOMAIN,
                offline_issue_id,
                is_fixable=False,
                severity=issue_registry.IssueSeverity.WARNING,
                translation_key="p1_meter_offline",
                translation_placeholders={"name": device_name},
            )

    def _register_fetch_success() -> None:
        nonlocal consecutive_failures
        if consecutive_failures >= OFFLINE_AFTER_CONSECUTIVE_FAILURES:
            coordinator.device_online = True
            issue_registry.async_delete_issue(hass, DOMAIN, offline_issue_id)
        consecutive_failures = 0

    async def async_update_data():
        try:
            session = async_get_clientsession(hass)
            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=request_timeout)) as response:
                response.raise_for_status()
                data = await response.json()
                _register_fetch_success()
                return data
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout while fetching data from Powerbaas API (%s)", api_url)
            _register_fetch_failure()
            raise
        except aiohttp.ClientError as err:
            _LOGGER.error("HTTP error while fetching data from Powerbaas API (%s): %s", api_url, err)
            _register_fetch_failure()
            raise

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )
    # Entities key their availability off this instead of the coordinator's
    # own last_update_success, so a single missed poll doesn't flip every
    # sensor unavailable - mirrors the Boiler Controller's offline grace
    # period (OFFLINE_AFTER_CONSECUTIVE_FAILURES).
    coordinator.device_online = True

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady from err

    return {
        "coordinator": coordinator,
        "host": api_url,
        "name": device_name,
    }


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clear any open offline repair issue; platform unload is handled by the caller."""
    issue_registry.async_delete_issue(hass, DOMAIN, f"p1_meter_offline_{entry.entry_id}")
