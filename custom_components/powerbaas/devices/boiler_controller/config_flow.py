"""Config flow steps for the Boiler Controller device type."""
import logging

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ...const import (
    DOMAIN,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_BOILER_CONTROLLER,
    DEVICE_TYPE_P1_METER,
)
from .const import (
    BATTERY_SENSOR_TYPE_NET,
    BATTERY_SENSOR_TYPE_NONE,
    BATTERY_SENSOR_TYPE_SPLIT,
    BATTERY_SENSOR_TYPES,
    CONF_BATTERY_CHARGE_NEGATIVE,
    CONF_BATTERY_CHARGE_SENSOR,
    CONF_BATTERY_DISCHARGE_SENSOR,
    CONF_BATTERY_FULL_SOC,
    CONF_BATTERY_MAX_CHARGE_WATTS,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SENSOR_TYPE,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_TAPER_SOC,
    CONF_BATTERY_TAPER_WATTS,
    CONF_SAFETY_MARGIN_WATTS,
    DEFAULT_BATTERY_FULL_SOC,
    DEFAULT_BATTERY_MAX_CHARGE_WATTS,
    DEFAULT_SAFETY_MARGIN_WATTS,
    CONF_POWER_SENSOR,
    CONF_POWER_SENSOR_TYPE,
    CONF_RETURN_SENSOR,
    CONF_USAGE_SENSOR,
    POWER_SENSOR_TYPE_NET,
    POWER_SENSOR_TYPE_SPLIT,
    POWER_SENSOR_TYPES,
    CONF_DEVICE_URL,
    CONF_DEVICE_ID,
    BC_HOST_PREFIX,
)
from ..p1_meter.const import P1_POWER_USAGE_UNIQUE_ID_SUFFIX

_LOGGER = logging.getLogger(__name__)


def _find_config_entry_for_device(hass, device_id: str | None, *, exclude_entry_id: str | None = None):
    """Return an existing entry that already manages this BC device."""
    if not device_id:
        return None

    normalized = device_id.lower()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if exclude_entry_id and entry.entry_id == exclude_entry_id:
            continue
        entry_device_id = entry.data.get(CONF_DEVICE_ID)
        if entry_device_id and entry_device_id.lower() == normalized:
            return entry
        if entry.unique_id and entry.unique_id.lower() == normalized:
            return entry

    return None


def _find_powerbaas_p1_power_sensor(hass) -> str | None:
    """Return the net Power Usage entity of a configured Powerbaas P1 Meter.

    Used to preselect the P1 as the Boiler Controller's power source, like the
    Homey app's auto-link. Multiple P1 Meters isn't a supported setup (one grid
    connection, one meter), so the first one found is used.
    """
    registry = er.async_get(hass)
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_P1_METER:
            continue
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}{P1_POWER_USAGE_UNIQUE_ID_SUFFIX}"
        )
        if not entity_id:
            continue
        reg_entry = registry.async_get(entity_id)
        if reg_entry and reg_entry.disabled_by is None:
            return entity_id
    return None


class DeviceValidationMixin:
    """Shared helpers for validating BC device connectivity in flows."""

    def _normalize_url(self, url: str) -> str:
        return url.strip().rstrip("/") if url else url

    async def _test_device_connection(self, url: str) -> bool:
        """Test connectivity to the BC device by calling /api/status."""
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                f"{url}/api/status", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                return resp.status == 200
        except aiohttp.ClientError as err:
            _LOGGER.warning("Device connection error: %s", err)
        except Exception as err:  # pragma: no cover
            _LOGGER.error("Unexpected device test error: %s", err)
        return False

    @staticmethod
    def _derive_device_id(url: str, hostname: str | None = None) -> str | None:
        """Derive a stable device identifier from the hostname or URL."""
        if hostname:
            short = hostname.rstrip(".").split(".")[0].lower()
            if short:
                return short
        if not url:
            return None
        # Fall back to the host part of the URL
        import re
        m = re.search(r"https?://([^/:]+)", url)
        if m:
            return m.group(1).lower()
        return None

    async def _get_return_sensors(self):
        """Get list of candidate power-like sensors from HA.

        Includes both dedicated return/usage sensors (always positive) and
        net power sensors (negative when exporting); the user picks which
        flavour they configured via the power sensor type field. A Powerbaas
        P1 Meter's net power sensor is always listed first.
        """
        sensors = {}
        p1_sensor = _find_powerbaas_p1_power_sensor(self.hass)
        if p1_sensor:
            state = self.hass.states.get(p1_sensor)
            friendly_name = state.attributes.get("friendly_name", p1_sensor) if state else p1_sensor
            sensors[p1_sensor] = f"{friendly_name} ({p1_sensor}) [W] - Powerbaas P1"
        for entity_id in self.hass.states.async_entity_ids("sensor"):
            if entity_id in sensors:
                continue
            state = self.hass.states.get(entity_id)
            if not state:
                continue
            if any(
                keyword in entity_id.lower()
                for keyword in [
                    "power",
                    "watt",
                    "electricity",
                    "current_consumption",
                    "current_production",
                    "energy",
                    "verbruik",
                    "opwek",
                    "net_power",
                ]
            ):
                try:
                    float(state.state)
                    unit = state.attributes.get("unit_of_measurement", "")
                    if any(u in unit.lower() for u in ["w", "kw", "watt"]):
                        friendly_name = state.attributes.get("friendly_name", entity_id)
                        sensors[entity_id] = f"{friendly_name} ({entity_id}) [{unit}]"
                except (ValueError, TypeError):
                    continue
        return sensors

    def _sensor_type_selector(self) -> selector.SelectSelector:
        """Selector for picking the power-sensor flavour (net vs split)."""
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": POWER_SENSOR_TYPE_NET, "label": "Net power sensor (single signed sensor)"},
                    {"value": POWER_SENSOR_TYPE_SPLIT, "label": "Separate return and usage sensors"},
                ],
                mode=selector.SelectSelectorMode.LIST,
            )
        )

    def _sensor_type_schema(self, default: str) -> vol.Schema:
        """Schema for picking the power-sensor flavour (net vs split)."""
        return vol.Schema({
            vol.Required(CONF_POWER_SENSOR_TYPE, default=default): self._sensor_type_selector(),
        })

    @staticmethod
    def _required_with_default(key: str, default: str | None) -> vol.Required:
        """vol.Required with a default only when there is one.

        voluptuous treats default=None as a real default of None rather than
        "no default", which would prefill the dropdown with an invalid value.
        """
        if default:
            return vol.Required(key, default=default)
        return vol.Required(key)

    def _sensor_dropdown(self, sensors: dict, default=None):
        """Build a dropdown selector from the candidate sensors mapping."""
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": key, "label": value}
                    for key, value in sensors.items()
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )


# Cleared when "No home battery" is picked.
_BATTERY_KEYS = (
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_CHARGE_NEGATIVE,
    CONF_BATTERY_CHARGE_SENSOR,
    CONF_BATTERY_DISCHARGE_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_FULL_SOC,
    CONF_BATTERY_MAX_CHARGE_WATTS,
    CONF_BATTERY_TAPER_SOC,
    CONF_BATTERY_TAPER_WATTS,
)


def _watts_selector(max_watts: int) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=max_watts, step=10, unit_of_measurement="W",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _soc_selector(min_soc: int) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=min_soc, max=100, step=1, unit_of_measurement="%",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _validate_battery_settings(user_input: dict) -> dict:
    """Taper level and watts go together, below full, and need a SoC sensor."""
    taper_soc = user_input.get(CONF_BATTERY_TAPER_SOC)
    taper_watts = user_input.get(CONF_BATTERY_TAPER_WATTS)
    if taper_soc is None and taper_watts is None:
        return {}
    if taper_soc is None:
        return {CONF_BATTERY_TAPER_SOC: "taper_incomplete"}
    if taper_watts is None:
        return {CONF_BATTERY_TAPER_WATTS: "taper_incomplete"}
    if not user_input.get(CONF_BATTERY_SOC_SENSOR):
        return {CONF_BATTERY_TAPER_SOC: "taper_needs_soc_sensor"}
    if taper_soc >= user_input[CONF_BATTERY_FULL_SOC]:
        return {CONF_BATTERY_TAPER_SOC: "taper_not_below_full"}
    return {}


def _optional_with_default(key: str, default) -> vol.Optional:
    """vol.Optional with a suggested value only when there is one.

    An EntitySelector can't be cleared again once given a vol default, so
    the current value is passed as a suggestion instead.
    """
    if default:
        return vol.Optional(key, description={"suggested_value": default})
    return vol.Optional(key)


class BatteryPriorityStepsMixin:
    """Battery-priority steps shared by the config and options flows.

    Runs after the power sensor step. Subclasses provide
    ``_battery_current()`` (values to prefill) and ``_battery_done()``
    (create or update the entry); answers accumulate in ``self.data``.
    """

    def _battery_current(self) -> dict:
        raise NotImplementedError

    async def _battery_done(self):
        raise NotImplementedError

    def _battery_settings_schema(self, current: dict) -> dict:
        """SoC sensor and charge limits, shown only once a battery is picked."""
        return {
            _optional_with_default(
                CONF_BATTERY_SOC_SENSOR, current.get(CONF_BATTERY_SOC_SENSOR)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_BATTERY_FULL_SOC,
                default=current.get(CONF_BATTERY_FULL_SOC, DEFAULT_BATTERY_FULL_SOC),
            ): _soc_selector(50),
            vol.Required(
                CONF_BATTERY_MAX_CHARGE_WATTS,
                default=current.get(CONF_BATTERY_MAX_CHARGE_WATTS, DEFAULT_BATTERY_MAX_CHARGE_WATTS),
            ): _watts_selector(10000),
            _optional_with_default(
                CONF_BATTERY_TAPER_SOC, current.get(CONF_BATTERY_TAPER_SOC)
            ): _soc_selector(1),
            _optional_with_default(
                CONF_BATTERY_TAPER_WATTS, current.get(CONF_BATTERY_TAPER_WATTS)
            ): _watts_selector(10000),
        }

    def _store_battery_settings(self, user_input: dict) -> None:
        self.data[CONF_BATTERY_SOC_SENSOR] = user_input.get(CONF_BATTERY_SOC_SENSOR)
        self.data[CONF_BATTERY_FULL_SOC] = int(user_input[CONF_BATTERY_FULL_SOC])
        self.data[CONF_BATTERY_MAX_CHARGE_WATTS] = int(user_input[CONF_BATTERY_MAX_CHARGE_WATTS])
        for key in (CONF_BATTERY_TAPER_SOC, CONF_BATTERY_TAPER_WATTS):
            value = user_input.get(key)
            self.data[key] = int(value) if value is not None else None

    async def async_step_battery_priority(self, user_input=None):
        """Pick the battery sensor flavour (or none) and the safety margin.

        Battery-only settings live on the follow-up sensor step, since a
        form can't hide fields depending on another field's value.
        """
        current = self._battery_current()

        if user_input is not None:
            battery_type = user_input[CONF_BATTERY_SENSOR_TYPE]
            self.data[CONF_BATTERY_SENSOR_TYPE] = battery_type
            self.data[CONF_SAFETY_MARGIN_WATTS] = int(user_input[CONF_SAFETY_MARGIN_WATTS])
            if battery_type == BATTERY_SENSOR_TYPE_NET:
                return await self.async_step_battery_sensor_net()
            if battery_type == BATTERY_SENSOR_TYPE_SPLIT:
                return await self.async_step_battery_sensor_split()
            for key in _BATTERY_KEYS:
                self.data[key] = None
            return await self._battery_done()

        current_type = current.get(CONF_BATTERY_SENSOR_TYPE, BATTERY_SENSOR_TYPE_NONE)
        if current_type not in BATTERY_SENSOR_TYPES:
            current_type = BATTERY_SENSOR_TYPE_NONE
        schema = vol.Schema({
            vol.Required(CONF_BATTERY_SENSOR_TYPE, default=current_type): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=BATTERY_SENSOR_TYPES,
                    mode=selector.SelectSelectorMode.LIST,
                    translation_key=CONF_BATTERY_SENSOR_TYPE,
                )
            ),
            vol.Required(
                CONF_SAFETY_MARGIN_WATTS,
                default=current.get(CONF_SAFETY_MARGIN_WATTS, DEFAULT_SAFETY_MARGIN_WATTS),
            ): _watts_selector(1000),
        })
        return self.async_show_form(step_id="battery_priority", data_schema=schema)

    async def async_step_battery_sensor_net(self, user_input=None):
        """Pick a single signed battery power sensor, SoC and limits."""
        errors = {}
        current = self._battery_current()

        if user_input is not None:
            errors = _validate_battery_settings(user_input)
        if user_input is not None and not errors:
            self.data[CONF_BATTERY_POWER_SENSOR] = user_input[CONF_BATTERY_POWER_SENSOR]
            self.data[CONF_BATTERY_CHARGE_NEGATIVE] = bool(user_input[CONF_BATTERY_CHARGE_NEGATIVE])
            self.data[CONF_BATTERY_CHARGE_SENSOR] = None
            self.data[CONF_BATTERY_DISCHARGE_SENSOR] = None
            self._store_battery_settings(user_input)
            return await self._battery_done()

        schema = vol.Schema({
            self._required_with_default(
                CONF_BATTERY_POWER_SENSOR, current.get(CONF_BATTERY_POWER_SENSOR)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_BATTERY_CHARGE_NEGATIVE,
                default=bool(current.get(CONF_BATTERY_CHARGE_NEGATIVE, False)),
            ): selector.BooleanSelector(),
            **self._battery_settings_schema(current),
        })
        return self.async_show_form(
            step_id="battery_sensor_net", data_schema=schema, errors=errors
        )

    async def async_step_battery_sensor_split(self, user_input=None):
        """Pick separate battery charge and discharge sensors, SoC and limits."""
        errors = {}
        current = self._battery_current()

        if user_input is not None:
            if user_input[CONF_BATTERY_CHARGE_SENSOR] == user_input[CONF_BATTERY_DISCHARGE_SENSOR]:
                errors[CONF_BATTERY_DISCHARGE_SENSOR] = "sensors_must_differ"
            else:
                errors = _validate_battery_settings(user_input)
            if not errors:
                self.data[CONF_BATTERY_CHARGE_SENSOR] = user_input[CONF_BATTERY_CHARGE_SENSOR]
                self.data[CONF_BATTERY_DISCHARGE_SENSOR] = user_input[CONF_BATTERY_DISCHARGE_SENSOR]
                self.data[CONF_BATTERY_POWER_SENSOR] = None
                self.data[CONF_BATTERY_CHARGE_NEGATIVE] = None
                self._store_battery_settings(user_input)
                return await self._battery_done()

        schema = vol.Schema({
            self._required_with_default(
                CONF_BATTERY_CHARGE_SENSOR, current.get(CONF_BATTERY_CHARGE_SENSOR)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            self._required_with_default(
                CONF_BATTERY_DISCHARGE_SENSOR, current.get(CONF_BATTERY_DISCHARGE_SENSOR)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            **self._battery_settings_schema(current),
        })
        return self.async_show_form(
            step_id="battery_sensor_split", data_schema=schema, errors=errors
        )


class BoilerControllerFlowMixin(BatteryPriorityStepsMixin, DeviceValidationMixin):
    """Config flow steps for adding a Boiler Controller."""

    async def _async_zeroconf_boiler_controller(self, discovery_info: ZeroconfServiceInfo):
        """Handle Zeroconf discovery for pb-bc-* BC modules.

        Called by ``PowerbaasConfigFlow.async_step_zeroconf`` after it
        determines the discovered hostname belongs to a Boiler Controller;
        not a direct HA entry point itself since only one class in the
        flow's MRO can own ``async_step_zeroconf``.
        """
        self.data = getattr(self, "data", {})
        hostname = discovery_info.hostname or discovery_info.name
        if not hostname:
            return self.async_abort(reason="unsupported_device")

        hostname = hostname.rstrip(".")
        short_hostname = hostname.split(".")[0].lower()
        if not any(short_hostname.startswith(prefix) for prefix in BC_HOST_PREFIX):
            return self.async_abort(reason="unsupported_device")

        ip_address = str(discovery_info.host) if discovery_info.host else None
        device_url = f"http://{ip_address}" if ip_address else f"http://{hostname}"
        device_id = short_hostname

        existing_entry = _find_config_entry_for_device(self.hass, device_id)
        if existing_entry:
            return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured(updates={CONF_DEVICE_URL: device_url})

        self.data[CONF_DEVICE_URL] = device_url
        self.data[CONF_DEVICE_ID] = device_id
        self.context["title_placeholders"] = {"name": f"Boiler Controller ({short_hostname})"}

        return await self.async_step_boiler_controller()

    async def async_step_boiler_controller(self, user_input=None):
        """Handle the initial step for adding a Boiler Controller."""
        _LOGGER.debug("Boiler Controller config flow started")

        self.data = getattr(self, "data", {})
        self.data[CONF_DEVICE_TYPE] = DEVICE_TYPE_BOILER_CONTROLLER
        errors = {}

        if user_input is not None:
            # Store user input and proceed to the device URL
            self.data.update(user_input)
            return await self.async_step_device_config()

        schema = vol.Schema({
            vol.Required("name", default="Boiler Controller"): str,
        })

        return self.async_show_form(step_id="boiler_controller", data_schema=schema, errors=errors)

    async def async_step_power_sensor(self, user_input=None):
        """Pick the power-sensor flavour (net or split)."""
        errors = {}

        if user_input is not None:
            sensor_type = user_input.get(CONF_POWER_SENSOR_TYPE)
            if sensor_type not in POWER_SENSOR_TYPES:
                errors[CONF_POWER_SENSOR_TYPE] = "invalid_sensor_type"
            else:
                self.data[CONF_POWER_SENSOR_TYPE] = sensor_type
                if sensor_type == POWER_SENSOR_TYPE_SPLIT:
                    return await self.async_step_power_sensor_split()
                return await self.async_step_power_sensor_net()

        return self.async_show_form(
            step_id="power_sensor",
            data_schema=self._sensor_type_schema(POWER_SENSOR_TYPE_NET),
            errors=errors,
        )

    async def async_step_power_sensor_net(self, user_input=None):
        """Pick a single net (signed) power sensor."""
        sensors = await self._get_return_sensors()
        if not sensors:
            return self.async_abort(reason="no_power_sensors")

        if user_input is not None:
            self.data[CONF_POWER_SENSOR] = user_input[CONF_POWER_SENSOR]
            # Clear any leftover split-mode keys
            self.data.pop(CONF_RETURN_SENSOR, None)
            self.data.pop(CONF_USAGE_SENSOR, None)
            return await self.async_step_battery_priority()

        schema = vol.Schema({
            self._required_with_default(
                CONF_POWER_SENSOR, _find_powerbaas_p1_power_sensor(self.hass)
            ): self._sensor_dropdown(sensors),
        })
        return self.async_show_form(step_id="power_sensor_net", data_schema=schema)

    async def async_step_power_sensor_split(self, user_input=None):
        """Pick separate return (export) and usage (import) sensors."""
        errors = {}
        sensors = await self._get_return_sensors()
        if not sensors:
            return self.async_abort(reason="no_power_sensors")

        if user_input is not None:
            if user_input[CONF_RETURN_SENSOR] == user_input[CONF_USAGE_SENSOR]:
                errors[CONF_USAGE_SENSOR] = "sensors_must_differ"
            else:
                self.data[CONF_RETURN_SENSOR] = user_input[CONF_RETURN_SENSOR]
                self.data[CONF_USAGE_SENSOR] = user_input[CONF_USAGE_SENSOR]
                self.data.pop(CONF_POWER_SENSOR, None)
                return await self.async_step_battery_priority()

        schema = vol.Schema({
            vol.Required(CONF_RETURN_SENSOR): self._sensor_dropdown(sensors),
            vol.Required(CONF_USAGE_SENSOR): self._sensor_dropdown(sensors),
        })
        return self.async_show_form(
            step_id="power_sensor_split", data_schema=schema, errors=errors
        )

    def _battery_current(self) -> dict:
        return self.data

    async def _battery_done(self):
        # None marks "cleared" in the options flow; nothing to clear here.
        data = {key: value for key, value in self.data.items() if value is not None}
        return self.async_create_entry(
            title=self.data.get("name", "Boiler Controller"),
            data=data,
        )

    async def async_step_device_config(self, user_input=None):
        """Handle BC device connection configuration."""
        errors = {}

        stored_url = self.data.get(CONF_DEVICE_URL, "")
        default_url = self._normalize_url(stored_url)

        if user_input is not None:
            device_url = self._normalize_url(user_input.get(CONF_DEVICE_URL, ""))

            if not device_url.startswith(("http://", "https://")):
                errors[CONF_DEVICE_URL] = "invalid_url"
            elif not await self._test_device_connection(device_url):
                errors[CONF_DEVICE_URL] = "cannot_connect_device"
            else:
                device_id = self._derive_device_id(
                    device_url, self.data.get(CONF_DEVICE_ID)
                )
                if not device_id:
                    errors[CONF_DEVICE_URL] = "cannot_identify"
                else:
                    existing_entry = _find_config_entry_for_device(self.hass, device_id)
                    if existing_entry:
                        return self.async_abort(reason="already_configured")

                    if self.unique_id is None:
                        await self.async_set_unique_id(device_id)

                    self.data.update(
                        {CONF_DEVICE_URL: device_url, CONF_DEVICE_ID: device_id}
                    )
                    return await self.async_step_power_sensor()

            default_url = device_url

        schema = vol.Schema({
            vol.Required(CONF_DEVICE_URL, default=default_url): str
        })

        return self.async_show_form(
            step_id="device_config",
            data_schema=schema,
            errors=errors,
            description_placeholders={"example_url": "http://pb-bc-xxxx.local"},
        )


class BoilerControllerOptionsFlow(
    BatteryPriorityStepsMixin, DeviceValidationMixin, config_entries.OptionsFlow
):
    """Handle options flow for Boiler Controller.

    The entry-point method must be named ``async_step_init`` (Home Assistant
    calls it by that fixed name), but the step_id used for the first form is
    namespaced as "boiler_controller_init" so it doesn't collide with other
    Powerbaas device types sharing this domain's options flow.
    """

    def __init__(self, config_entry):
        super().__init__()
        self._config_entry = config_entry
        self.data = {}

    async def async_step_boiler_controller_init(self, user_input=None):
        """Mandatory HA entry point; has no form of its own.

        Immediately delegates to the device URL step. Home Assistant tracks
        the "current step" by whichever step_id was last shown via
        ``async_show_form``, so once that step renders, follow-up submissions
        invoke ``async_step_device_config`` directly rather than this method.
        """
        return await self.async_step_device_config(user_input)

    # Delegate the standard init step to our namespaced step so that HA can
    # track the current step correctly and avoid collisions with other device types.
    async_step_init = async_step_boiler_controller_init

    async def async_step_device_config(self, user_input=None):
        """Ask for/update the BC device URL, first in the edit wizard."""
        errors = {}
        default_url = self._normalize_url(self._config_entry.data.get(CONF_DEVICE_URL, ""))

        if user_input is not None:
            device_url = self._normalize_url(user_input.get(CONF_DEVICE_URL, ""))

            if not device_url.startswith(("http://", "https://")):
                errors[CONF_DEVICE_URL] = "invalid_url"
            elif not await self._test_device_connection(device_url):
                errors[CONF_DEVICE_URL] = "cannot_connect_device"
            else:
                device_id = self._derive_device_id(
                    device_url, self._config_entry.data.get(CONF_DEVICE_ID)
                )
                existing_entry = _find_config_entry_for_device(
                    self.hass, device_id, exclude_entry_id=self._config_entry.entry_id
                )
                if existing_entry:
                    errors[CONF_DEVICE_URL] = "device_in_use"
                else:
                    self.data[CONF_DEVICE_URL] = device_url
                    if device_id:
                        self.data[CONF_DEVICE_ID] = device_id
                    return await self.async_step_power_sensor()

            default_url = device_url

        schema = vol.Schema({vol.Required(CONF_DEVICE_URL, default=default_url): str})

        return self.async_show_form(
            step_id="device_config",
            data_schema=schema,
            errors=errors,
            description_placeholders={"example_url": "http://pb-bc-xxxx.local"},
        )

    async def async_step_power_sensor(self, user_input=None):
        """Pick the power-sensor flavour (net or split) when changing the sensor."""
        errors = {}
        current_type = self._config_entry.data.get(
            CONF_POWER_SENSOR_TYPE, POWER_SENSOR_TYPE_NET
        )

        if user_input is not None:
            sensor_type = user_input.get(CONF_POWER_SENSOR_TYPE)
            if sensor_type not in POWER_SENSOR_TYPES:
                errors[CONF_POWER_SENSOR_TYPE] = "invalid_sensor_type"
            else:
                self.data[CONF_POWER_SENSOR_TYPE] = sensor_type
                if sensor_type == POWER_SENSOR_TYPE_SPLIT:
                    return await self.async_step_power_sensor_split()
                return await self.async_step_power_sensor_net()

        return self.async_show_form(
            step_id="power_sensor",
            data_schema=self._sensor_type_schema(current_type),
            errors=errors,
        )

    async def async_step_power_sensor_net(self, user_input=None):
        """Pick the single net sensor when changing the sensor."""
        sensors = await self._get_return_sensors()
        if not sensors:
            return self.async_abort(reason="no_power_sensors")

        # Switching from split to net leaves no current sensor: fall back to
        # the Powerbaas P1 Meter, same as when first adding the device.
        current_sensor = self._config_entry.data.get(
            CONF_POWER_SENSOR
        ) or _find_powerbaas_p1_power_sensor(self.hass)

        if user_input is not None:
            self.data[CONF_POWER_SENSOR] = user_input[CONF_POWER_SENSOR]
            self.data.pop(CONF_RETURN_SENSOR, None)
            self.data.pop(CONF_USAGE_SENSOR, None)
            return await self.async_step_battery_priority()

        schema = vol.Schema({
            self._required_with_default(
                CONF_POWER_SENSOR, current_sensor
            ): self._sensor_dropdown(sensors),
        })
        return self.async_show_form(step_id="power_sensor_net", data_schema=schema)

    async def async_step_power_sensor_split(self, user_input=None):
        """Pick separate return + usage sensors when changing the sensor."""
        errors = {}
        sensors = await self._get_return_sensors()
        if not sensors:
            return self.async_abort(reason="no_power_sensors")

        current_return = self._config_entry.data.get(CONF_RETURN_SENSOR)
        current_usage = self._config_entry.data.get(CONF_USAGE_SENSOR)

        if user_input is not None:
            if user_input[CONF_RETURN_SENSOR] == user_input[CONF_USAGE_SENSOR]:
                errors[CONF_USAGE_SENSOR] = "sensors_must_differ"
            else:
                self.data[CONF_RETURN_SENSOR] = user_input[CONF_RETURN_SENSOR]
                self.data[CONF_USAGE_SENSOR] = user_input[CONF_USAGE_SENSOR]
                self.data.pop(CONF_POWER_SENSOR, None)
                return await self.async_step_battery_priority()

        schema = vol.Schema({
            vol.Required(
                CONF_RETURN_SENSOR, default=current_return
            ): self._sensor_dropdown(sensors),
            vol.Required(
                CONF_USAGE_SENSOR, default=current_usage
            ): self._sensor_dropdown(sensors),
        })
        return self.async_show_form(
            step_id="power_sensor_split", data_schema=schema, errors=errors
        )

    def _battery_current(self) -> dict:
        return {**self._config_entry.data, **self.data}

    async def _battery_done(self):
        return await self._finalize()

    async def _finalize(self):
        """Persist the accumulated changes (URL and/or sensor selection) and reload."""
        new_data = dict(self._config_entry.data)
        new_data.update(self.data)
        # None marks a key cleared in this run (e.g. split battery sensors
        # after switching to a single one).
        new_data = {key: value for key, value in new_data.items() if value is not None}

        self.hass.config_entries.async_update_entry(
            self._config_entry,
            data=new_data,
            options=dict(self._config_entry.options),
            unique_id=self.data.get(CONF_DEVICE_ID, self._config_entry.unique_id),
        )
        await self.hass.config_entries.async_reload(self._config_entry.entry_id)
        # HA replaces entry.options with this data - pass the current options
        # (control mode, heating watts, ...) through instead of wiping them.
        return self.async_create_entry(title="", data=dict(self._config_entry.options))
