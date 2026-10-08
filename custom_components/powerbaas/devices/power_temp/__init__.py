"""Powerbaas PowerTemp (meter cabinet temperature monitor) support."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, issue_registry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ...const import DOMAIN, OFFLINE_AFTER_CONSECUTIVE_FAILURES
from .client import PowerTempClient, PowerTempCommandError
from .const import (
    CONF_DEVICE_URL,
    DEFAULT_POLL_INTERVAL,
    MAX_PORTS,
    NEW_SENSOR_ISSUE_PREFIX,
    port_from_device,
)
from .entity import hub_device_info

_LOGGER = logging.getLogger(__name__)


def new_sensor_issue_id(entry_id: str, port: int) -> str:
    return f"{NEW_SENSOR_ISSUE_PREFIX}{entry_id}_{port}"


class PowerTempCoordinator(DataUpdateCoordinator):
    """Poll /api/sensors, /api/system and /api/config, with the shared offline grace period.

    Also owns config changes (thresholds, delta, per-port sensor config) and
    the "new sensor found" repair issues, since both need the device's
    current config rather than any single entity's view of it.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: PowerTempClient,
        device_name: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_power_temp",
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
        )
        self.client = client
        self.config_entry = entry
        self.device_name = device_name
        self.device_url = client.base_url
        self.device_online = True
        # Ports the sensor platform has created entities for; a port is
        # dropped again when its sub-device is deleted, so it's re-added if
        # the sensor is ever plugged back in.
        self.known_ports: set[int] = set()
        # Ports removed on purpose while unplugged. The firmware keeps listing
        # a recently seen, unconfigured port as "missing" for a while (so a
        # failing new sensor isn't silent); ignore those until it forgets the
        # port or a sensor is plugged in again, so the removed sub-device
        # doesn't reappear and no "new sensor" issue is raised for it.
        self.ignored_ports: set[int] = set()
        self._new_sensor_ports: set[int] = set()
        self._consecutive_failures = 0
        self._offline_issue_id = f"power_temp_offline_{entry.entry_id}"

    async def _async_update_data(self) -> dict[str, Any]:
        sensors = await self.client.async_get_sensors()
        if sensors is None:
            self._register_failure()
            raise UpdateFailed(
                f"Powerbaas PowerTemp sensors request failed for {self.device_name}"
            )

        self._register_success()
        system = await self.client.async_get_system()
        config = await self.client.async_get_config()
        if config is None:
            # Config only changes on a user action; keep the last known one
            # rather than flipping every config entity unavailable.
            config = (self.data or {}).get("config") or {}

        # Ports come and go (a new sensor plugged in, an unconfigured one
        # unplugged), so index them by port number for entities.
        ports = {
            item["port"]: item
            for item in sensors.get("temperatures") or []
            if isinstance(item, dict) and isinstance(item.get("port"), int)
        }
        self.ignored_ports = {
            port
            for port in self.ignored_ports
            if port in ports and not ports[port].get("present")
        }
        self._sync_new_sensor_issues(ports)
        return {
            "sensors": sensors,
            "system": system or {},
            "config": config,
            "ports": ports,
        }

    def _sync_new_sensor_issues(self, ports: dict[int, dict]) -> None:
        """Raise a fixable repair issue per detected-but-unconfigured sensor.

        Kept open while such a sensor is "missing" too: the firmware only
        lists an unconfigured port for a while after it was last seen, so
        adopting it is what keeps a failure visible for good.
        """
        new_ports = {
            port
            for port, item in ports.items()
            if not item.get("configured") and port not in self.ignored_ports
        }
        for port in new_ports - self._new_sensor_ports:
            issue_registry.async_create_issue(
                self.hass,
                DOMAIN,
                new_sensor_issue_id(self.config_entry.entry_id, port),
                is_fixable=True,
                severity=issue_registry.IssueSeverity.WARNING,
                translation_key="power_temp_new_sensor",
                translation_placeholders={"name": self.device_name, "port": str(port)},
                data={"entry_id": self.config_entry.entry_id, "port": port},
            )
        for port in self._new_sensor_ports - new_ports:
            issue_registry.async_delete_issue(
                self.hass, DOMAIN, new_sensor_issue_id(self.config_entry.entry_id, port)
            )
        self._new_sensor_ports = new_ports

    def _register_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures == OFFLINE_AFTER_CONSECUTIVE_FAILURES:
            self.device_online = False
            _LOGGER.warning(
                "Powerbaas PowerTemp offline for %s after %s consecutive failed fetches",
                self.device_name,
                self._consecutive_failures,
            )
            issue_registry.async_create_issue(
                self.hass,
                DOMAIN,
                self._offline_issue_id,
                is_fixable=False,
                severity=issue_registry.IssueSeverity.WARNING,
                translation_key="power_temp_offline",
                translation_placeholders={"name": self.device_name},
            )
            # DataUpdateCoordinator only notifies listeners on the first
            # failed refresh after a success - see CLAUDE.md.
            self.async_update_listeners()

    def _register_success(self) -> None:
        if self._consecutive_failures >= OFFLINE_AFTER_CONSECUTIVE_FAILURES:
            self.device_online = True
            issue_registry.async_delete_issue(self.hass, DOMAIN, self._offline_issue_id)
            self.async_update_listeners()
        self._consecutive_failures = 0

    def configured_sensor(self, port: int) -> dict | None:
        for sensor in ((self.data or {}).get("config") or {}).get("sensors") or []:
            if sensor.get("port") == port:
                return sensor
        return None

    async def async_update_config(self, body: dict[str, Any]) -> None:
        """POST a partial config, then refresh so levels/statuses reflect it."""
        await self.client.async_update_config(body)
        await self.async_refresh()

    async def _async_update_sensor_list(
        self, mutate: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
    ) -> None:
        # The firmware replaces the whole sensor list on POST, so read the
        # device's current list right before changing it (not the cached
        # one) to avoid undoing an edit made in the web UI since last poll.
        config = await self.client.async_get_config()
        if config is None:
            raise PowerTempCommandError("cannot_connect")
        sensors = [dict(sensor) for sensor in config.get("sensors") or []]
        await self.async_update_config({"sensors": mutate(sensors)})

    async def async_save_sensor(
        self,
        port: int,
        *,
        name: str | None = None,
        offset_c: float | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Add (adopt) or update one port's sensor config."""

        def mutate(sensors: list[dict[str, Any]]) -> list[dict[str, Any]]:
            sensor = next((s for s in sensors if s.get("port") == port), None)
            if sensor is None:
                sensor = {"port": port, "name": "", "offsetC": 0, "enabled": True, "ambient": False}
                sensors.append(sensor)
            if name is not None:
                sensor["name"] = name
            if offset_c is not None:
                sensor["offsetC"] = offset_c
            if enabled is not None:
                sensor["enabled"] = enabled
            return sensors

        await self._async_update_sensor_list(mutate)

    async def async_remove_sensor(self, port: int) -> None:
        """Remove a port from the sensor config.

        Still plugged in: it becomes a new (unconfigured) sensor again.
        Unplugged: it's ignored until the firmware forgets it.
        """
        port_data = ((self.data or {}).get("ports") or {}).get(port) or {}
        # Before the POST: it refreshes, and must not raise a "new sensor" issue for this port.
        ignore = not port_data.get("present") and port not in self.ignored_ports
        if ignore:
            self.ignored_ports.add(port)
        try:
            await self._async_update_sensor_list(
                lambda sensors: [s for s in sensors if s.get("port") != port]
            )
        except PowerTempCommandError:
            if ignore:
                self.ignored_ports.discard(port)
            raise

    async def async_set_ambient_port(self, port: int | None) -> None:
        """Make ``port`` the (single) ambient sensor, adopting it if needed; None clears it."""

        def mutate(sensors: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if port is not None and not any(s.get("port") == port for s in sensors):
                sensors.append({"port": port, "name": "", "offsetC": 0, "enabled": True})
            for sensor in sensors:
                sensor["ambient"] = sensor.get("port") == port
            return sensors

        await self._async_update_sensor_list(mutate)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Set up a Powerbaas PowerTemp device and return its runtime data."""
    device_url = entry.data.get(CONF_DEVICE_URL)
    if not device_url:
        raise ConfigEntryNotReady("No device URL configured for Powerbaas PowerTemp.")

    device_name = entry.title or "Powerbaas PowerTemp"
    client = PowerTempClient(hass, device_url)

    if not await client.async_test_connection():
        raise ConfigEntryNotReady(
            f"Device communication error occurred for {device_name}"
        )

    coordinator = PowerTempCoordinator(hass, entry, client, device_name)
    await coordinator.async_config_entry_first_refresh()

    # Register the hub before any platform runs: port sub-devices point at
    # it via via_device, which must already exist when they're created.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **hub_device_info(coordinator, entry)
    )

    return {
        "coordinator": coordinator,
        "name": device_name,
        "device_url": client.base_url,
    }


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clear open repair issues; platform unload is handled by the caller.

    New-sensor issues are raised again on the next first refresh if still relevant.
    """
    issue_registry.async_delete_issue(hass, DOMAIN, f"power_temp_offline_{entry.entry_id}")
    for port in range(1, MAX_PORTS + 1):
        issue_registry.async_delete_issue(hass, DOMAIN, new_sensor_issue_id(entry.entry_id, port))


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow deleting a port's sub-device once its sensor is unplugged.

    Also removes the port from the device's sensor config, so it stops
    being reported as "missing". The hub device itself can't be deleted
    this way (remove the integration entry instead).
    """
    port = port_from_device(entry.entry_id, device_entry)
    if port is None:
        return False

    coordinator: PowerTempCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    port_data = ((coordinator.data or {}).get("ports") or {}).get(port) or {}
    if port_data.get("present"):
        _LOGGER.warning(
            "Not removing PowerTemp port %s of %s: a sensor is still connected",
            port,
            coordinator.device_name,
        )
        return False

    if coordinator.configured_sensor(port) is not None:
        try:
            await coordinator.async_remove_sensor(port)
        except PowerTempCommandError as err:
            _LOGGER.warning("Removing PowerTemp port %s failed: %s", port, err.code)
            return False
    else:
        coordinator.ignored_ports.add(port)

    coordinator.known_ports.discard(port)
    return True
