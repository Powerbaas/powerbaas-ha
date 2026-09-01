"""Coordinator for the Boiler Controller: polling, offline detection, and all
control/calibration logic (kept on this class rather than split onto
entities, since it's genuinely device-specific business logic, not
boilerplate)."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import issue_registry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ...const import DOMAIN, OFFLINE_AFTER_CONSECUTIVE_FAILURES
from .bc_client import BCClient
from .const import (
    BOILER_MODE_AUTO,
    BOILER_MODE_MANUAL,
    BOILER_MODE_OFF,
    BOILER_MODE_ON,
    BOILER_MODES,
    CALIBRATION_POLL_SECONDS,
    CONF_DEVICE_URL,
    CONF_POLL_INTERVAL,
    CONF_POWER_SENSOR,
    CONF_POWER_SENSOR_TYPE,
    CONF_RETURN_SENSOR,
    CONF_USAGE_SENSOR,
    DEFAULT_MANUAL_WATTS,
    DEFAULT_MAX_HEATING_WATTS,
    DEFAULT_MIN_HEATING_WATTS,
    DEFAULT_POLL_INTERVAL,
    MAX_HEATING_WATTS_OPTIONS,
    POWER_SENSOR_TYPE_NET,
    POWER_SENSOR_TYPE_SPLIT,
    POWER_SENSOR_TYPES,
)

_LOGGER = logging.getLogger(__name__)


class BoilerControllerCoordinator(DataUpdateCoordinator):
    """Poll /api/status and /api/system, and own BC's control/calibration logic.

    coordinator.data holds both poll-driven fields ("status", "system") and
    command-driven fields ("control_mode", "manual_watts",
    "max_heating_watts", "min_heating_watts", "calibration_active") - the
    latter are carried forward on every poll cycle (see
    _async_update_data), since a fresh poll must not wipe out state that
    isn't re-fetched from the device every cycle.
    """

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, integration_version: str | None
    ) -> None:
        device_url = config_entry.data[CONF_DEVICE_URL]

        # Power-sensor configuration. Two flavours are supported:
        #   - POWER_SENSOR_TYPE_NET:   single signed sensor (negative = export).
        #   - POWER_SENSOR_TYPE_SPLIT: two sensors, one for grid return (export)
        #     and one for grid usage (import); both always >= 0.
        sensor_type = config_entry.data.get(CONF_POWER_SENSOR_TYPE, POWER_SENSOR_TYPE_NET)
        power_sensor_type = (
            sensor_type if sensor_type in POWER_SENSOR_TYPES else POWER_SENSOR_TYPE_NET
        )
        if power_sensor_type == POWER_SENSOR_TYPE_SPLIT:
            power_sensor_id = None
            return_sensor_id = config_entry.data[CONF_RETURN_SENSOR]
            usage_sensor_id = config_entry.data[CONF_USAGE_SENSOR]
            tracked_entities = [return_sensor_id, usage_sensor_id]
        else:
            power_sensor_id = config_entry.data[CONF_POWER_SENSOR]
            return_sensor_id = None
            usage_sensor_id = None
            tracked_entities = [power_sensor_id]

        poll_interval = config_entry.options.get(
            CONF_POLL_INTERVAL,
            config_entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_boiler_controller",
            update_interval=timedelta(seconds=poll_interval),
        )

        self.config_entry = config_entry
        self.integration_version = integration_version
        self.device_url = device_url
        self.power_sensor_type = power_sensor_type
        self.power_sensor_id = power_sensor_id
        self.return_sensor_id = return_sensor_id
        self.usage_sensor_id = usage_sensor_id
        self._tracked_entities = tracked_entities
        self.poll_interval = poll_interval
        self.device_client = BCClient(hass, device_url)

        stored_mode = config_entry.options.get("control_mode", BOILER_MODE_OFF)
        control_mode = stored_mode if stored_mode in BOILER_MODES else BOILER_MODE_OFF

        # Max heating watts mirrors the device's own maxHeatingWatts (kept in sync
        # via polling - see _apply_max_heating_watts_from_status); the stored
        # option is only the seed used before the first successful status poll.
        stored_max_watts = config_entry.options.get("max_heating_watts", DEFAULT_MAX_HEATING_WATTS)
        max_heating_watts = (
            int(stored_max_watts)
            if int(stored_max_watts) in MAX_HEATING_WATTS_OPTIONS
            else DEFAULT_MAX_HEATING_WATTS
        )

        stored_watts = config_entry.options.get("manual_watts", DEFAULT_MANUAL_WATTS)
        manual_watts = max(0, min(max_heating_watts, int(stored_watts)))

        stored_min_watts = config_entry.options.get("min_heating_watts", DEFAULT_MIN_HEATING_WATTS)
        min_heating_watts = max(0, min(max_heating_watts, int(stored_min_watts)))

        # Seed from persisted config-entry options so entities have sane
        # values even before the first poll completes.
        self.data = {
            "status": None,
            "system": None,
            "control_mode": control_mode,
            "manual_watts": manual_watts,
            "max_heating_watts": max_heating_watts,
            "min_heating_watts": min_heating_watts,
            "calibration_active": False,
        }

        self.device_online = True
        self._consecutive_failures = 0
        self._offline_issue_id = f"boiler_controller_offline_{config_entry.entry_id}"
        self._current_dimmer_percentage: int | None = None
        self._last_control_update = None
        self._last_power_value = None
        self._last_auto_update = None
        self._missing_sensor_log: dict[str, Any] = {}

        self._calibration_lock = asyncio.Lock()
        self._calibration_cancel_requested = False
        self._calibration_previous_mode: str | None = None

        _LOGGER.debug(
            "Initialized BoilerControllerCoordinator: type=%s, tracked=%s, Device URL=%s, poll_interval=%ds",
            self.power_sensor_type,
            self._tracked_entities,
            self.device_url,
            self.poll_interval,
        )

    async def _async_validate_configuration(self) -> None:
        """Log whether the configured power sensor(s) currently exist (informational only)."""
        for entity_id in self._tracked_entities:
            sensor_state = self.hass.states.get(entity_id)
            if not sensor_state:
                _LOGGER.info(
                    "Power sensor %s not found yet - controller will start and wait for entity",
                    entity_id,
                )
            else:
                _LOGGER.info(
                    "Found power sensor: %s (current value: %s)", entity_id, sensor_state.state
                )

    # ------------------------------------------------------------------
    # Polling / offline detection
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        # Fetch system info first: Device Info's firmware version reads off
        # coordinator.data["system"], which must already reflect this
        # cycle's data by the time listeners are notified below - otherwise
        # it would always lag one cycle behind the status update.
        system = await self.device_client.async_get_system()
        status = await self.device_client.async_get_status()

        if status is None:
            self._register_failure()
            raise UpdateFailed(
                f"Boiler Controller status request failed for {self.config_entry.title}"
            )

        self._register_success()

        data = dict(self.data or {})
        data["status"] = status
        if system is not None:
            data["system"] = (system or {}).get("system") or {}

        self._update_cached_brightness(status)
        self._apply_max_heating_watts_from_status(data, status)

        return data

    def _register_failure(self) -> None:
        """Track a failed /api/status fetch; flip to offline after the threshold."""
        self._consecutive_failures += 1
        if self._consecutive_failures == OFFLINE_AFTER_CONSECUTIVE_FAILURES:
            self.device_online = False
            if self.data:
                self.data = {**self.data, "status": None, "system": None}
            _LOGGER.warning(
                "BC device offline for %s after %s consecutive failed polls",
                self.config_entry.title,
                self._consecutive_failures,
            )
            issue_registry.async_create_issue(
                self.hass,
                DOMAIN,
                self._offline_issue_id,
                is_fixable=False,
                severity=issue_registry.IssueSeverity.WARNING,
                translation_key="boiler_controller_offline",
                translation_placeholders={"name": self.config_entry.title},
            )
            # DataUpdateCoordinator only calls async_update_listeners() for
            # the *first* failed refresh after a success (see its
            # last_update_success/previous_update_success check) - every
            # failure after that is silently skipped. Without this, entities
            # never learn device_online flipped to False and stay "available".
            self.async_update_listeners()

    def _register_success(self) -> None:
        """Record a successful /api/status fetch; flip back online after an outage."""
        if self._consecutive_failures >= OFFLINE_AFTER_CONSECUTIVE_FAILURES:
            self.device_online = True
            _LOGGER.info("BC device back online for %s", self.config_entry.title)
            issue_registry.async_delete_issue(self.hass, DOMAIN, self._offline_issue_id)
            self.async_update_listeners()
        self._consecutive_failures = 0

    # ------------------------------------------------------------------
    # Auto-control (triggered by power-sensor state changes)
    # ------------------------------------------------------------------

    @callback
    async def _async_power_sensor_changed(self, event: Event) -> None:
        """Handle power sensor state changes.

        Only relevant in Auto mode - Manual/On/Off targets don't depend on
        the power sensor, so reacting to it there would just re-send the
        same command on every sensor tick and spuriously bump
        last_control_update.
        """
        data = self.data or {}
        if data.get("calibration_active"):
            _LOGGER.debug("Skipping power sensor update while calibration is active")
            return

        if data.get("control_mode") != BOILER_MODE_AUTO:
            return

        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return

        # Throttle auto-mode updates to once per poll_interval
        now = dt_util.utcnow()
        if self._last_auto_update is not None:
            elapsed = (now - self._last_auto_update).total_seconds()
            if elapsed < DEFAULT_POLL_INTERVAL:
                return

        # Skip if state hasn't actually changed or is unavailable
        if (old_state and new_state.state == old_state.state) or new_state.state in (
            "unknown",
            "unavailable",
            "none",
        ):
            _LOGGER.debug("Skipping update - state unchanged or unavailable")
            return

        # Compute the latest signed surplus and only update when it moved enough.
        new_surplus = self._compute_surplus()
        if new_surplus is None:
            return

        if self._last_power_value is not None and abs(new_surplus - self._last_power_value) < 1:
            _LOGGER.debug(
                "Skipping update - surplus change too small: %.1fW",
                abs(new_surplus - self._last_power_value),
            )
            return

        self._last_power_value = new_surplus
        _LOGGER.debug(
            "Power sensor %s changed (state %s -> %s); surplus now %.1f W",
            event.data.get("entity_id"),
            old_state.state if old_state else "unknown",
            new_state.state,
            new_surplus,
        )

        await self._async_update()

    async def _async_update(self, *args: Any) -> None:
        """Apply the current control mode to the device."""
        try:
            data = self.data or {}
            if data.get("calibration_active"):
                _LOGGER.debug("Calibration active - skipping automatic adjustment")
                return

            control_mode = data.get("control_mode")
            if control_mode == BOILER_MODE_OFF:
                await self._set_heating_percentage(0, source=BOILER_MODE_OFF)
                return

            if control_mode == BOILER_MODE_ON:
                await self._set_heating_percentage(100, source=BOILER_MODE_ON)
                return

            if control_mode == BOILER_MODE_MANUAL:
                await self._apply_manual_watts()
                return

            # Auto mode: compute signed surplus (positive=export, negative=import)
            # and combine it with the boiler's current draw.
            surplus = self._compute_surplus()
            if surplus is None:
                _LOGGER.debug("Could not read power sensor value - sensor may not be ready yet")
                return

            self._last_power_value = surplus
            _LOGGER.debug("Current grid surplus: %.1f W", surplus)

            # Available watts for the boiler is the current boiler draw plus the
            # signed surplus. When importing, surplus is negative and the boiler
            # is throttled down; when exporting it is allowed to ramp up.
            # Note: the boiler does clamping itself to its own maxHeatingWatts,
            # but we also clamp here to the configured max heating watts just to be safe.
            boiler_watts = self._extract_boiler_consumption()
            max_heating_watts = data.get("max_heating_watts", 0)
            available_watts = max(0, min(max_heating_watts, int(boiler_watts + surplus)))
            min_heating_watts = data.get("min_heating_watts", 0)
            if min_heating_watts:
                available_watts = max(available_watts, min_heating_watts)

            _LOGGER.debug(
                "Auto mode: surplus=%.1fW, boiler=%.1fW, available=%dW",
                surplus,
                boiler_watts,
                available_watts,
            )

            await self.device_client.async_set_target_watts(available_watts)

            timestamp = dt_util.utcnow()
            self._last_auto_update = timestamp
            self._last_control_update = timestamp

        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Error during controller update: %s", err)
        finally:
            # Redraws every CoordinatorEntity on every auto-control tick
            # (mirrors the per-entity power-sensor listeners this replaces).
            self.async_update_listeners()

    def _read_sensor_watts(self, entity_id: str) -> float | None:
        """Read a single sensor and return its value normalised to Watts.

        Returns ``None`` when the entity is missing, unavailable or the state
        cannot be parsed as a number.
        """
        state = self.hass.states.get(entity_id)
        if not state:
            now = dt_util.utcnow()
            last = self._missing_sensor_log.get(entity_id)
            if last is None or (now - last).total_seconds() > 60:
                _LOGGER.warning("Power sensor %s not found - check if entity exists", entity_id)
                self._missing_sensor_log[entity_id] = now
            return None

        if state.state in ("unknown", "unavailable", "none"):
            _LOGGER.debug("Power sensor %s is unavailable (state: %s)", entity_id, state.state)
            return None

        try:
            value = float(state.state)
        except (ValueError, TypeError) as err:
            _LOGGER.warning(
                "Error parsing power sensor value '%s' for %s: %s", state.state, entity_id, err
            )
            return None

        unit = self._get_state_unit(state)
        value = self._normalize_power_unit(value, unit)

        # Clear stale missing-sensor log entry once data flows again
        self._missing_sensor_log.pop(entity_id, None)

        return value

    def _compute_surplus(self) -> float | None:
        """Return the signed grid surplus in Watts.

        Positive values mean we are exporting to the grid, negative values
        mean we are importing. ``None`` is returned when the required
        sensor(s) cannot be read.
        """
        if self.power_sensor_type == POWER_SENSOR_TYPE_SPLIT:
            return_watts = self._read_sensor_watts(self.return_sensor_id)
            usage_watts = self._read_sensor_watts(self.usage_sensor_id)
            if return_watts is None or usage_watts is None:
                return None
            # Both sensors are always >= 0; the difference gives the signed
            # surplus (export minus import).
            return float(return_watts) - float(usage_watts)

        # Net mode: single signed sensor, negative when exporting.
        net_watts = self._read_sensor_watts(self.power_sensor_id)
        if net_watts is None:
            return None
        return -float(net_watts)

    def _extract_boiler_consumption(self) -> float:
        """Return the latest device-reported boiler power in watts."""
        status = (self.data or {}).get("status") or {}
        try:
            return float(status.get("power", 0))
        except (TypeError, ValueError):
            return 0.0

    async def _set_heating_percentage(self, percentage: int, *, source: str = BOILER_MODE_AUTO) -> None:
        """Set heating percentage on the BC device."""
        if source == BOILER_MODE_MANUAL:
            context = "manual override"
        elif source == "calibration":
            context = "calibration"
        elif source == BOILER_MODE_ON:
            context = "always on"
        elif source == BOILER_MODE_OFF:
            context = "always off"
        else:
            context = "auto calculation"

        clamped = max(0, min(100, int(percentage)))
        if self._current_dimmer_percentage == clamped:
            _LOGGER.debug("BC heating already at %s%% (%s) - skipping request", clamped, context)
            return
        _LOGGER.info("BC heating request (%s): set to %s%%", context, clamped)
        try:
            success = await self.device_client.async_set_heating_percentage(clamped)
            self._current_dimmer_percentage = clamped
            if not success:
                _LOGGER.warning("Failed to set BC heating to %s%%", clamped)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Error setting BC heating percentage: %s", err)

    def _update_cached_brightness(self, status: dict | None) -> None:
        """Cache the heating percentage reported by the device status."""
        if not status:
            return
        value = status.get("heatingPercentage")
        if value is None:
            return
        try:
            parsed = max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return
        self._current_dimmer_percentage = parsed

    def _apply_max_heating_watts_from_status(self, data: dict[str, Any], status: dict | None) -> None:
        """Sync max_heating_watts from the device's status into `data` (mutated
        in place - `data` is about to become the new coordinator.data).

        The device is the source of truth for maxHeatingWatts; this keeps the
        Max Heating Power select in sync whether it changed here or was set
        directly on the device, and clamps min_heating_watts down if needed.
        """
        if not status:
            return
        value = status.get("maxHeatingWatts")
        if value is None:
            return
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return
        if parsed == data.get("max_heating_watts"):
            return
        data["max_heating_watts"] = parsed
        self._persist_options(max_heating_watts=parsed)
        if data.get("min_heating_watts", 0) > parsed:
            data["min_heating_watts"] = parsed
            self._persist_options(min_heating_watts=parsed)

    def _persist_options(self, **updates: Any) -> None:
        """Store runtime preferences in the config entry options."""
        if not updates:
            return
        new_options = dict(self.config_entry.options)
        changed = False
        for key, value in updates.items():
            if value is None:
                continue
            if new_options.get(key) == value:
                continue
            new_options[key] = value
            changed = True
        if changed:
            self.hass.config_entries.async_update_entry(self.config_entry, options=new_options)

    @staticmethod
    def _get_state_unit(state) -> str:
        unit = state.attributes.get("unit_of_measurement")
        if not unit:
            unit = state.attributes.get("native_unit_of_measurement")
        return str(unit).strip() if unit else ""

    @staticmethod
    def _normalize_power_unit(power_value: float, unit: str) -> float:
        if not unit:
            return power_value
        cleaned = unit.strip().lower()
        if cleaned.startswith("kw") or "kilowatt" in cleaned:
            return power_value * 1000
        return power_value

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_request_calibration_cancel(self) -> bool:
        """Signal the active calibration run to stop after the current step."""
        if not (self.data or {}).get("calibration_active"):
            return False
        self._calibration_cancel_requested = True
        ok = await self.device_client.async_calibration_stop()
        _LOGGER.info(
            "Calibration stop requested for %s (device accepted: %s)",
            self.config_entry.title,
            ok,
        )
        return True

    async def async_set_control_mode(self, mode: str) -> None:
        """Set control mode (auto, manual, on, off)."""
        if (self.data or {}).get("calibration_active"):
            raise RuntimeError("Cannot change control mode during calibration")
        if mode not in BOILER_MODES:
            raise ValueError(f"Unsupported control mode: {mode}")
        if mode == self.data.get("control_mode"):
            return
        self._persist_options(control_mode=mode)
        self.async_set_updated_data({**self.data, "control_mode": mode})
        await self._async_update()

    async def async_set_manual_watts(self, watts: int) -> None:
        """Store manual target watts and apply when manual mode is active."""
        if (self.data or {}).get("calibration_active"):
            raise RuntimeError("Cannot change manual watts during calibration")
        # the watts are already clamped to the max heating watts
        # but just to be safe, we clamp it again here to ensure it's within valid bounds
        watts = max(0, min(self.data["max_heating_watts"], int(watts)))
        if watts == self.data.get("manual_watts"):
            return
        self._persist_options(manual_watts=watts)
        self.async_set_updated_data({**self.data, "manual_watts": watts})
        if self.data.get("control_mode") == BOILER_MODE_MANUAL:
            await self._apply_manual_watts()

    async def _apply_manual_watts(self) -> None:
        """Send the stored manual target watts to the device."""
        watts = self.data.get("manual_watts", 0)
        _LOGGER.debug("Applying manual power override: %sW", watts)
        success = await self.device_client.async_set_target_watts(watts)
        if success:
            self._last_control_update = dt_util.utcnow()
        await self.async_request_refresh()

    async def async_set_max_heating_watts(self, watts: int) -> None:
        """Set the device's configurable max heating wattage (one of MAX_HEATING_WATTS_OPTIONS)."""
        watts = int(watts)
        if watts not in MAX_HEATING_WATTS_OPTIONS:
            raise ValueError(f"Unsupported max heating watts: {watts}")
        await self.device_client.async_set_max_heating_watts(watts)
        # Pull the device's authoritative value back rather than assuming success;
        # this also clamps min_heating_watts down if it now exceeds the new max.
        await self.async_request_refresh()

    async def async_set_min_heating_watts(self, watts: int) -> None:
        """Store the min heating watts floor (HA-side only, applied in Auto mode)."""
        watts = max(0, min(self.data["max_heating_watts"], int(watts)))
        if watts == self.data.get("min_heating_watts"):
            return
        self._persist_options(min_heating_watts=watts)
        self.async_set_updated_data({**self.data, "min_heating_watts": watts})

    async def async_set_ssr(self, on: bool) -> None:
        """Turn the SSR relay on/off, applying the device's confirmed response.

        Applies the reported state via async_set_updated_data() rather than
        async_request_refresh(): the latter goes through
        DataUpdateCoordinator's debounced-refresh cooldown (10s by default -
        the same as this coordinator's poll_interval), so a toggle landing
        while a periodic poll is already in flight gets deferred a full
        cooldown, while that in-flight poll (which read the device before
        the command took effect) lands afterwards and overwrites the switch
        back to its old state - the switch flips to the new state, reverts,
        then flips again once the deferred refresh finally runs.
        """
        reported = await self.device_client.async_set_ssr(on)
        if reported is None:
            return
        status = dict((self.data or {}).get("status") or {})
        status["ssr"] = {**(status.get("ssr") or {}), "on": reported}
        self.async_set_updated_data({**self.data, "status": status})

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    async def async_run_calibration(self) -> None:
        """Start an automated calibration run on the device and wait for completion."""
        if self._calibration_lock.locked():
            raise RuntimeError("A calibration run is already in progress")

        async with self._calibration_lock:
            self._set_calibration_active(True)
            self._calibration_cancel_requested = False
            self._enter_calibration_mode()
            try:
                ok = await self.device_client.async_calibration_run()
                if not ok:
                    _LOGGER.warning(
                        "Device rejected calibration start for %s", self.config_entry.title
                    )
                    return

                _LOGGER.info(
                    "Calibration started on device for %s - polling for completion",
                    self.config_entry.title,
                )

                seen_running = False
                while True:
                    await asyncio.sleep(CALIBRATION_POLL_SECONDS)
                    cal_data = await self.device_client.async_get_calibration()
                    if cal_data is None:
                        _LOGGER.warning("Lost contact with device during calibration")
                        break

                    run = cal_data.get("run", {})
                    state = run.get("state", "idle")
                    _LOGGER.debug(
                        "Calibration poll: state=%s step=%s percent=%s watts=%s",
                        state,
                        run.get("step"),
                        run.get("currentPercent"),
                        run.get("lastSampleWatts"),
                    )

                    # state values per API: "idle", "running", "done"
                    if state == "running":
                        seen_running = True

                    # Exit on "done", or on "idle" after having seen "running"
                    # (idle is also the initial state before calibration begins)
                    if state == "done" or (seen_running and state == "idle"):
                        _LOGGER.info("Calibration completed for %s", self.config_entry.title)
                        break

                    if run.get("error"):
                        _LOGGER.error("Calibration error from device: %s", run["error"])
                        break

                    if self._calibration_cancel_requested:
                        break

            finally:
                self._calibration_cancel_requested = False
                self._set_calibration_active(False)
                self._exit_calibration_mode()
                await self.async_request_refresh()
                await self._async_update()

    def _enter_calibration_mode(self) -> None:
        """Switch to manual mode for the duration of calibration."""
        control_mode = self.data.get("control_mode")
        self._calibration_previous_mode = control_mode
        if control_mode not in (BOILER_MODE_OFF, BOILER_MODE_MANUAL):
            self.async_set_updated_data({**self.data, "control_mode": BOILER_MODE_OFF})

    def _exit_calibration_mode(self) -> None:
        """Restore the control mode that was active before calibration."""
        restored = self._calibration_previous_mode or BOILER_MODE_OFF
        self._calibration_previous_mode = None
        self.async_set_updated_data({**self.data, "control_mode": restored})

    def _set_calibration_active(self, active: bool) -> None:
        self.async_set_updated_data({**self.data, "calibration_active": active})
