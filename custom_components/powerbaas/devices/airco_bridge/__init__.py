"""Airco Bridge device support for the Powerbaas integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ...const import DOMAIN, OFFLINE_AFTER_CONSECUTIVE_FAILURES
from .client import AircoClient
from .const import CONF_DEVICE_URL, DEFAULT_POLL_INTERVAL

_LOGGER = logging.getLogger(__name__)


class AircoBridgeCoordinator(DataUpdateCoordinator):
    """Poll /api/status and /api/system, with the shared offline grace period."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: AircoClient,
        device_name: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_airco_bridge",
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
        )
        self.client = client
        self.config_entry = entry
        self.device_name = device_name
        self.device_url = client.base_url
        self.device_online = True
        self.ir_types: list[dict[str, Any]] = []
        self._consecutive_failures = 0
        self._offline_issue_id = f"airco_bridge_offline_{entry.entry_id}"

    async def _async_update_data(self) -> dict[str, Any]:
        status = await self.client.async_get_status()
        if status is None:
            self._register_failure()
            raise UpdateFailed(f"Airco Bridge status request failed for {self.device_name}")

        self._register_success()
        if not self.ir_types:
            self.ir_types = await self.client.async_get_types() or []
        system = await self.client.async_get_system()
        return {
            "airco": status.get("airco") or {},
            "temperature": status.get("temperature") or {},
            "system": (system or {}).get("system") or {},
        }

    def _register_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures == OFFLINE_AFTER_CONSECUTIVE_FAILURES:
            self.device_online = False
            _LOGGER.warning(
                "Airco Bridge offline for %s after %s consecutive failed fetches",
                self.device_name,
                self._consecutive_failures,
            )
            issue_registry.async_create_issue(
                self.hass,
                DOMAIN,
                self._offline_issue_id,
                is_fixable=False,
                severity=issue_registry.IssueSeverity.WARNING,
                translation_key="airco_bridge_offline",
                translation_placeholders={"name": self.device_name},
            )
            # DataUpdateCoordinator only calls async_update_listeners() for
            # the *first* failed refresh after a success (see its
            # last_update_success/previous_update_success check) - every
            # failure after that is silently skipped. Without this, entities
            # never learn device_online flipped to False and stay "available".
            self.async_update_listeners()

    def _register_success(self) -> None:
        if self._consecutive_failures >= OFFLINE_AFTER_CONSECUTIVE_FAILURES:
            self.device_online = True
            issue_registry.async_delete_issue(self.hass, DOMAIN, self._offline_issue_id)
            self.async_update_listeners()
        self._consecutive_failures = 0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Set up an Airco Bridge device and return its runtime data."""
    device_url = entry.data.get(CONF_DEVICE_URL)
    if not device_url:
        raise ConfigEntryNotReady("No device URL configured for Airco Bridge.")

    device_name = entry.title or "Airco Bridge"
    client = AircoClient(hass, device_url)

    # Gate setup on the device being reachable right now, so an offline
    # device shows up as "Failed setup, will retry" on the Integrations page
    # (HA automatically retries with backoff) instead of silently succeeding.
    if not await client.async_test_connection():
        raise ConfigEntryNotReady(
            f"Device communication error occurred for {device_name}"
        )

    coordinator = AircoBridgeCoordinator(hass, entry, client, device_name)
    coordinator.ir_types = await client.async_get_types() or []
    await coordinator.async_config_entry_first_refresh()

    return {
        "coordinator": coordinator,
        "name": device_name,
        "device_url": client.base_url,
    }


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clear any open offline repair issue; platform unload is handled by the caller."""
    issue_registry.async_delete_issue(hass, DOMAIN, f"airco_bridge_offline_{entry.entry_id}")
