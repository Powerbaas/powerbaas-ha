import logging
import asyncio

from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers import issue_registry
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from ...const import DOMAIN, OFFLINE_AFTER_CONSECUTIVE_FAILURES
from .const import (
    CONF_POWER_SENSOR,
    CONF_POWER_SENSOR_TYPE,
    CONF_RETURN_SENSOR,
    CONF_USAGE_SENSOR,
    POWER_SENSOR_TYPE_NET,
    POWER_SENSOR_TYPE_SPLIT,
    POWER_SENSOR_TYPES,
    CONF_DEVICE_URL,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_MANUAL_WATTS,
    BOILER_MODE_AUTO,
    BOILER_MODE_MANUAL,
    BOILER_MODE_ON,
    BOILER_MODE_OFF,
    BOILER_MODES,
    CALIBRATION_POLL_SECONDS,
    MAX_HEATING_WATTS_OPTIONS,
    DEFAULT_MAX_HEATING_WATTS,
    DEFAULT_MIN_HEATING_WATTS,
)
from .bc_client import BCClient

_LOGGER = logging.getLogger(__name__)


class BoilerController:
    """Controller for managing boiler based on P1 data."""

    def __init__(self, hass: HomeAssistant, config_entry, integration_version: str | None):
        self.hass = hass
        self.config_entry = config_entry
        self.integration_version = integration_version
        self._cancel_listener = None
        self._poll_task = None
        self._polling_suspended = False
        self._last_control_update = None
        self._last_power_value = None
        self._last_auto_update = None
        self._device_status = None
        self._system_status = None
        self._device_online = True
        self._consecutive_poll_failures = 0
        self._offline_issue_id = f"boiler_controller_offline_{config_entry.entry_id}"
        self._current_dimmer_percentage: int | None = None
        self._dispatcher_signal = f"{DOMAIN}_{config_entry.entry_id}_device_status"
        self._mode_signal = f"{DOMAIN}_{config_entry.entry_id}_control_mode"
        self._manual_watts_signal = f"{DOMAIN}_{config_entry.entry_id}_manual_watts"
        self._calibration_signal = f"{DOMAIN}_{config_entry.entry_id}_calibration_state"
        self._max_heating_watts_signal = f"{DOMAIN}_{config_entry.entry_id}_max_heating_watts"
        self._min_heating_watts_signal = f"{DOMAIN}_{config_entry.entry_id}_min_heating_watts"

        # Configuration
        self.device_url = config_entry.data[CONF_DEVICE_URL]

        # Power-sensor configuration. Two flavours are supported:
        #   - POWER_SENSOR_TYPE_NET:   single signed sensor (negative = export).
        #   - POWER_SENSOR_TYPE_SPLIT: two sensors, one for grid return (export)
        #     and one for grid usage (import); both always >= 0.
        sensor_type = config_entry.data.get(CONF_POWER_SENSOR_TYPE, POWER_SENSOR_TYPE_NET)
        self.power_sensor_type = (
            sensor_type if sensor_type in POWER_SENSOR_TYPES else POWER_SENSOR_TYPE_NET
        )
        if self.power_sensor_type == POWER_SENSOR_TYPE_SPLIT:
            self.power_sensor_id = None
            self.return_sensor_id = config_entry.data[CONF_RETURN_SENSOR]
            self.usage_sensor_id = config_entry.data[CONF_USAGE_SENSOR]
            self._tracked_entities = [self.return_sensor_id, self.usage_sensor_id]
        else:
            self.power_sensor_id = config_entry.data[CONF_POWER_SENSOR]
            self.return_sensor_id = None
            self.usage_sensor_id = None
            self._tracked_entities = [self.power_sensor_id]

        self.device_client = BCClient(hass, self.device_url)

        stored_mode = config_entry.options.get("control_mode", BOILER_MODE_OFF)
        self._control_mode = stored_mode if stored_mode in BOILER_MODES else BOILER_MODE_OFF

        # Max heating watts mirrors the device's own maxHeatingWatts (kept in sync via
        # polling - see _update_cached_max_heating_watts); the stored option is only the
        # seed used before the first successful status poll.
        stored_max_watts = config_entry.options.get("max_heating_watts", DEFAULT_MAX_HEATING_WATTS)
        self._max_heating_watts = (
            int(stored_max_watts) if int(stored_max_watts) in MAX_HEATING_WATTS_OPTIONS else DEFAULT_MAX_HEATING_WATTS
        )

        stored_watts = config_entry.options.get("manual_watts", DEFAULT_MANUAL_WATTS)
        self._manual_watts = max(0, min(self._max_heating_watts, int(stored_watts)))

        stored_min_watts = config_entry.options.get("min_heating_watts", DEFAULT_MIN_HEATING_WATTS)
        self._min_heating_watts = max(0, min(self._max_heating_watts, int(stored_min_watts)))

        self._calibration_lock = asyncio.Lock()
        self._calibration_active = False
        self._calibration_cancel_requested = False
        self._calibration_previous_mode: str | None = None

        self.poll_interval = config_entry.options.get(
            CONF_POLL_INTERVAL,
            config_entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )

        _LOGGER.debug(
            "Initialized BoilerController: type=%s, tracked=%s, Device URL=%s, poll_interval=%ds",
            self.power_sensor_type,
            self._tracked_entities,
            self.device_url,
            self.poll_interval,
        )

    async def async_start(self):
        """Start the controller."""
        _LOGGER.info("Starting Boiler Controller")

        # Validate entities exist (informational only, always continue)
        await self._validate_configuration()

        # Note: Device reachability is gated before this is called (see __init__.py's
        # Note: async_setup_entry, which raises ConfigEntryNotReady otherwise).

        # Start listening to power sensor state changes
        self._cancel_listener = async_track_state_change_event(
            self.hass,
            self._tracked_entities,
            self._async_power_sensor_changed,
        )
        _LOGGER.info(
            "Started listening to power sensor state changes (type=%s) for: %s",
            self.power_sensor_type,
            self._tracked_entities,
        )

        # Start BC device polling task
        self._poll_task = self.hass.loop.create_task(self._async_poll_device())
        _LOGGER.info("Started device polling task with interval %ss", self.poll_interval)

        # Run initial update (will fail gracefully if entities don't exist yet)
        await self._async_update()

        _LOGGER.info("Boiler Controller started successfully")
        return True

    @callback
    async def _async_power_sensor_changed(self, event: Event):
        """Handle power sensor state changes.

        Only relevant in Auto mode - Manual/On/Off targets don't depend on
        the power sensor, so reacting to it there would just re-send the
        same command on every sensor tick and spuriously bump
        last_control_update.
        """
        if self._calibration_active:
            _LOGGER.debug("Skipping power sensor update while calibration is active")
            return

        if self._control_mode != BOILER_MODE_AUTO:
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

    async def async_stop(self):
        """Stop the controller."""
        _LOGGER.info("Stopping Boiler Controller")
        if self._cancel_listener:
            self._cancel_listener()
            self._cancel_listener = None
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        # Clear any offline issue if it exists, since the controller is being stopped
        issue_registry.async_delete_issue(self.hass, DOMAIN, self._offline_issue_id)

    async def _validate_configuration(self) -> bool:
        """Validate that all configured entities exist."""

        for entity_id in self._tracked_entities:
            sensor_state = self.hass.states.get(entity_id)
            if not sensor_state:
                _LOGGER.info(
                    "Power sensor %s not found yet - controller will start and wait for entity",
                    entity_id,
                )
            else:
                _LOGGER.info(
                    "Found power sensor: %s (current value: %s)",
                    entity_id,
                    sensor_state.state,
                )

        _LOGGER.info(
            "Controller configured (type=%s, sensors=%s, Device URL=%s)",
            self.power_sensor_type,
            self._tracked_entities,
            self.device_url,
        )
        return True

    async def _async_update(self, *args):
        """Update the controller - apply the current control mode."""
        if self._calibration_active:
            _LOGGER.debug("Calibration active - skipping automatic adjustment")
            return

        try:
            # Get current power consumption/production from P1
            if self._control_mode == BOILER_MODE_OFF:
                await self._set_heating_percentage(0, source=BOILER_MODE_OFF)
                return

            if self._control_mode == BOILER_MODE_ON:
                await self._set_heating_percentage(100, source=BOILER_MODE_ON)
                return

            if self._control_mode == BOILER_MODE_MANUAL:
                await self._apply_manual_watts()
                return

            # Auto mode: compute signed surplus (positive=export, negative=import)
            # and combine it with the boiler's current draw.
            surplus = self._compute_surplus()
            if surplus is None:
                _LOGGER.debug("Could not read power sensor value - sensor may not be ready yet")
                return

            # Store the current surplus value
            self._last_power_value = surplus
            _LOGGER.debug("Current grid surplus: %.1f W", surplus)

            # Available watts for the boiler is the current boiler draw plus the
            # signed surplus. When importing, surplus is negative and the boiler
            # is throttled down; when exporting it is allowed to ramp up.
            # Note: the boiler does clamping itself to its own maxHeatingWatts,
            # but we also clamp here to the configured max heating watts just to be safe.
            boiler_watts = self._extract_boiler_consumption()
            available_watts = max(0, min(self._max_heating_watts, int(boiler_watts + surplus)))
            if self._min_heating_watts:
                available_watts = max(available_watts, self._min_heating_watts)

            _LOGGER.debug(
                "Auto mode: surplus=%.1fW, boiler=%.1fW, available=%dW",
                surplus,
                boiler_watts,
                available_watts,
            )

            # Update the device with the new target watts based on available surplus
            await self.device_client.async_set_target_watts(available_watts)

            timestamp = dt_util.utcnow()
            self._last_auto_update = timestamp
            self._last_control_update = timestamp

        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Error during controller update: %s", err)

    def _read_sensor_watts(self, entity_id: str) -> float | None:
        """Read a single sensor and return its value normalised to Watts.

        Returns ``None`` when the entity is missing, unavailable or the state
        cannot be parsed as a number.
        """
        state = self.hass.states.get(entity_id)
        if not state:
            now = dt_util.utcnow()
            cache = getattr(self, "_missing_sensor_log", {})
            last = cache.get(entity_id)
            if last is None or (now - last).total_seconds() > 60:
                _LOGGER.warning(
                    "Power sensor %s not found - check if entity exists",
                    entity_id,
                )
                cache[entity_id] = now
                self._missing_sensor_log = cache
            return None

        if state.state in ("unknown", "unavailable", "none"):
            _LOGGER.debug(
                "Power sensor %s is unavailable (state: %s)", entity_id, state.state
            )
            return None

        try:
            value = float(state.state)
        except (ValueError, TypeError) as err:
            _LOGGER.warning(
                "Error parsing power sensor value '%s' for %s: %s",
                state.state,
                entity_id,
                err,
            )
            return None

        unit = self._get_state_unit(state)
        value = self._normalize_power_unit(value, unit)

        # Clear stale missing-sensor log entry once data flows again
        cache = getattr(self, "_missing_sensor_log", None)
        if cache and entity_id in cache:
            cache.pop(entity_id, None)

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

    async def _async_poll_device(self):
        """Poll the BC device status and system info at the configured interval."""
        while True:
            try:
                if not self._polling_suspended:
                    # Fetch system info first: entities (incl. Device Info's
                    # firmware version) refresh off the status dispatcher
                    # signal below, so _system_status must already reflect
                    # this cycle's data by the time that signal fires -
                    # otherwise they'd always be one cycle behind.
                    system = await self.device_client.async_get_system()
                    if system is not None:
                        self._system_status = system

                    status = await self.device_client.async_get_status()
                    if status is not None:
                        self._handle_status_success(status)
                    else:
                        self._register_poll_failure()

                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                _LOGGER.debug("Device polling task cancelled")
                break
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.error("Unexpected device polling error: %s", err)
                self._register_poll_failure()
                await asyncio.sleep(self.poll_interval)

    async def _async_refresh_device_status(self):
        """Force a device status refresh outside the poll loop."""
        try:
            status = await self.device_client.async_get_status()
            if status is None:
                self._register_poll_failure()
                return
            self._handle_status_success(status)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.debug("Manual device status refresh failed: %s", err)
            self._register_poll_failure()

    def _handle_status_success(self, status: dict) -> None:
        """Record a successful /api/status fetch and notify listeners."""
        self._consecutive_poll_failures = 0
        was_offline = not self._device_online
        self._device_online = True
        self._device_status = status
        self._update_cached_brightness(status)
        self._update_cached_max_heating_watts(status)
        async_dispatcher_send(self.hass, self._dispatcher_signal, status)
        if was_offline:
            _LOGGER.info("BC device back online for %s", self.config_entry.title)
            issue_registry.async_delete_issue(self.hass, DOMAIN, self._offline_issue_id)

    def _register_poll_failure(self) -> None:
        """Track a failed /api/status fetch; flip to offline after the threshold."""
        self._consecutive_poll_failures += 1
        if self._device_online and self._consecutive_poll_failures >= OFFLINE_AFTER_CONSECUTIVE_FAILURES:
            self._device_online = False
            self._device_status = None
            self._system_status = None
            _LOGGER.warning(
                "BC device offline for %s after %s consecutive failed polls",
                self.config_entry.title,
                self._consecutive_poll_failures,
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
            async_dispatcher_send(self.hass, self._dispatcher_signal, None)

    async def _set_heating_percentage(self, percentage: int, *, source: str = BOILER_MODE_AUTO):
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

    @property
    def device_firmware_version(self) -> str:
        """Return the device's own reported firmware version (system.firmwareVersion).

        Not to be confused with ``integration_version`` (the HACS package
        version) - this is what should show as "Firmware" in the Device Info
        card, matching how the P1 meter already does it.
        """
        system = (self._system_status or {}).get("system", {})
        return str(system.get("firmwareVersion", "Unknown"))

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.config_entry.entry_id)},
            "name": self.config_entry.title,
            "manufacturer": "Powerbaas",
            "model": "Boiler Controller",
            "sw_version": self.device_firmware_version,
            "configuration_url": self.device_url,
        }

    def get_status(self):
        """Get current controller status."""
        return {
            "last_control_update": self._last_control_update,
            "last_power_value": self._last_power_value,
            "power_sensor": self.power_sensor_id,
            "power_sensor_type": self.power_sensor_type,
            "return_sensor": self.return_sensor_id,
            "usage_sensor": self.usage_sensor_id,
            "device_url": self.device_url,
            "device_status": self._device_status,
            "system_status": self._system_status,
            "update_method": "event_driven",
            "poll_interval": self.poll_interval,
            "control_mode": self._control_mode,
            "manual_watts": self._manual_watts,
            "max_heating_watts": self._max_heating_watts,
            "min_heating_watts": self._min_heating_watts,
            "calibration_active": self._calibration_active,
            "device_online": self._device_online,
        }

    def get_device_status(self):
        """Expose latest device polling data (/api/status)."""
        return self._device_status

    def get_system_status(self):
        """Expose latest system info (/api/system)."""
        return self._system_status

    def get_device_status_signal(self):
        """Return dispatcher signal name for device status updates (/api/status)."""
        return self._dispatcher_signal

    def get_control_mode_signal(self):
        """Dispatcher signal for control mode changes."""
        return self._mode_signal

    def get_manual_watts_signal(self):
        """Dispatcher signal for manual watts changes."""
        return self._manual_watts_signal

    def get_max_heating_watts_signal(self):
        """Dispatcher signal for max heating watts changes."""
        return self._max_heating_watts_signal

    def get_min_heating_watts_signal(self):
        """Dispatcher signal for min heating watts changes."""
        return self._min_heating_watts_signal

    def get_calibration_state_signal(self):
        """Dispatcher signal fired when calibration state changes."""
        return self._calibration_signal

    @property
    def control_mode(self) -> str:
        return self._control_mode

    @property
    def manual_watts(self) -> int:
        return self._manual_watts

    @property
    def max_heating_watts(self) -> int:
        return self._max_heating_watts

    @property
    def min_heating_watts(self) -> int:
        return self._min_heating_watts

    @property
    def is_calibration_active(self) -> bool:
        """Return True if a calibration run is currently in progress."""
        return self._calibration_active

    @property
    def is_device_online(self) -> bool:
        """Return False after OFFLINE_AFTER_CONSECUTIVE_FAILURES consecutive failed polls."""
        return self._device_online

    async def async_request_calibration_cancel(self) -> bool:
        """Signal the active calibration run to stop after the current step."""
        if not self._calibration_active:
            return False
        self._calibration_cancel_requested = True
        ok = await self.device_client.async_calibration_stop()
        _LOGGER.info(
            "Calibration stop requested for %s (device accepted: %s)",
            self.config_entry.title,
            ok,
        )
        return True

    async def async_set_control_mode(self, mode: str):
        """Set control mode (auto, manual, on, off)."""
        if self._calibration_active:
            raise RuntimeError("Cannot change control mode during calibration")
        if mode not in BOILER_MODES:
            raise ValueError(f"Unsupported control mode: {mode}")
        if mode == self._control_mode:
            return
        self._control_mode = mode
        self._persist_controller_options(control_mode=mode)
        async_dispatcher_send(self.hass, self._mode_signal, mode)
        await self._async_update()

    async def async_set_manual_watts(self, watts: int):
        """Store manual target watts and apply when manual mode is active."""
        if self._calibration_active:
            raise RuntimeError("Cannot change manual watts during calibration")
        # the watts are already clamped to the max heating watts
        # but just to be safe, we clamp it again here to ensure it's within valid bounds
        watts = max(0, min(self._max_heating_watts, int(watts)))
        if watts == self._manual_watts:
            return
        self._manual_watts = watts
        self._persist_controller_options(manual_watts=self._manual_watts)
        async_dispatcher_send(self.hass, self._manual_watts_signal, watts)
        if self._control_mode == BOILER_MODE_MANUAL:
            await self._apply_manual_watts()

    async def _apply_manual_watts(self):
        """Send the stored manual target watts to the device."""
        _LOGGER.debug("Applying manual power override: %sW", self._manual_watts)
        success = await self.device_client.async_set_target_watts(self._manual_watts)
        if success:
            self._last_control_update = dt_util.utcnow()
        await self._async_refresh_device_status()

    async def async_set_max_heating_watts(self, watts: int):
        """Set the device's configurable max heating wattage (one of MAX_HEATING_WATTS_OPTIONS)."""
        watts = int(watts)
        if watts not in MAX_HEATING_WATTS_OPTIONS:
            raise ValueError(f"Unsupported max heating watts: {watts}")
        await self.device_client.async_set_max_heating_watts(watts)
        # Pull the device's authoritative value back rather than assuming success;
        # this also clamps min_heating_watts down if it now exceeds the new max.
        await self._async_refresh_device_status()

    async def async_set_min_heating_watts(self, watts: int):
        """Store the min heating watts floor (HA-side only, applied in Auto mode)."""
        watts = max(0, min(self._max_heating_watts, int(watts)))
        if watts == self._min_heating_watts:
            return
        self._min_heating_watts = watts
        self._persist_controller_options(min_heating_watts=watts)
        async_dispatcher_send(self.hass, self._min_heating_watts_signal, watts)

    async def async_set_ssr(self, on: bool):
        """Turn the SSR relay on/off and refresh device status."""
        await self.device_client.async_set_ssr(on)
        await self._async_refresh_device_status()

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
                        "Device rejected calibration start for %s",
                        self.config_entry.title,
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
                await self._async_refresh_device_status()
                await self._async_update()

    def _extract_boiler_consumption(self) -> float:
        """Return the latest device-reported boiler power in watts."""
        status = self._device_status or {}
        try:
            return float(status.get("power", 0))
        except (TypeError, ValueError):
            return 0.0

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

    def _update_cached_max_heating_watts(self, status: dict | None) -> None:
        """Sync the local max heating watts cache from the device's status.

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
        if parsed == self._max_heating_watts:
            return
        self._max_heating_watts = parsed
        self._persist_controller_options(max_heating_watts=parsed)
        async_dispatcher_send(self.hass, self._max_heating_watts_signal, parsed)
        if self._min_heating_watts > parsed:
            self._min_heating_watts = parsed
            self._persist_controller_options(min_heating_watts=parsed)
            async_dispatcher_send(self.hass, self._min_heating_watts_signal, parsed)

    def _persist_controller_options(self, **updates):
        """Store controller runtime preferences in the config entry options."""
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
            self.hass.config_entries.async_update_entry(
                self.config_entry, options=new_options
            )

    def _enter_calibration_mode(self) -> None:
        """Switch to manual mode for the duration of calibration."""
        self._calibration_previous_mode = self._control_mode
        if self._control_mode not in (BOILER_MODE_OFF, BOILER_MODE_MANUAL):
            self._control_mode = BOILER_MODE_OFF
            async_dispatcher_send(self.hass, self._mode_signal, BOILER_MODE_OFF)

    def _exit_calibration_mode(self) -> None:
        """Restore the control mode that was active before calibration."""
        restored = self._calibration_previous_mode or BOILER_MODE_OFF
        self._control_mode = restored
        self._calibration_previous_mode = None
        async_dispatcher_send(self.hass, self._mode_signal, restored)

    def _suspend_polling(self) -> None:
        self._polling_suspended = True

    def _resume_polling(self) -> None:
        self._polling_suspended = False

    def _set_calibration_active(self, active: bool) -> None:
        self._calibration_active = active
        async_dispatcher_send(self.hass, self._calibration_signal, active)

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
