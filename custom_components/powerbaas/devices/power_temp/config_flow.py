"""Config flow steps for the Powerbaas PowerTemp device type."""
import logging
from urllib.parse import urlparse

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from ...const import (
    DOMAIN,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_POWER_TEMP,
    config_entry_unique_id,
)
from .client import PowerTempCommandError
from .const import (
    PT_HOST_PREFIX,
    CONF_DEVICE_ID,
    CONF_DEVICE_URL,
    DEFAULT_NAME,
    OFFSET_MAX_C,
    OFFSET_MIN_C,
    SENSOR_NAME_MAX_BYTES,
    port_label,
)

_LOGGER = logging.getLogger(__name__)

EXAMPLE_URL = "http://pb-pt-xxxxxxxxxxxx.local"

# Helpers are module-level (not mixin methods) on purpose: every device type's
# mixin shares PowerbaasConfigFlow's MRO, so a same-named method on another
# mixin could silently win - see tests/test_unique_id_collision.py.


def _normalize_url(url: str) -> str:
    return url.strip().rstrip("/") if url else url


def _short_hostname(hostname: str) -> str:
    return hostname.rstrip(".").split(".")[0].lower()


def _is_power_temp_hostname(hostname: str | None) -> bool:
    return bool(hostname) and _short_hostname(hostname).startswith(PT_HOST_PREFIX)


def _device_id_from_url(url: str) -> str | None:
    """Stable id from a URL; include non-default ports so two proxies on the same host differ."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    if parsed.port and parsed.port not in (80, 443):
        return f"{host}:{parsed.port}"
    return host


def _find_config_entry_for_device(hass, device_id: str | None, *, exclude_entry_id: str | None = None):
    """Return an existing entry that already manages this Powerbaas PowerTemp."""
    if not device_id:
        return None

    normalized = device_id.lower()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if exclude_entry_id and entry.entry_id == exclude_entry_id:
            continue
        if entry.data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_POWER_TEMP:
            continue
        entry_device_id = entry.data.get(CONF_DEVICE_ID)
        if entry_device_id and entry_device_id.lower() == normalized:
            return entry
        unique_id = (entry.unique_id or "").lower()
        if unique_id in (normalized, config_entry_unique_id(DEVICE_TYPE_POWER_TEMP, normalized)):
            return entry

    return None


async def _async_test_power_temp_connection(hass, url: str) -> bool:
    """Test connectivity by calling /api/sensors."""
    try:
        session = async_get_clientsession(hass)
        async with session.get(
            f"{url}/api/sensors", timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            return resp.status == 200
    except aiohttp.ClientError as err:
        _LOGGER.warning("Powerbaas PowerTemp connection error: %s", err)
    except Exception as err:  # pragma: no cover
        _LOGGER.error("Unexpected Powerbaas PowerTemp test error: %s", err)
    return False


async def _async_fetch_power_temp_hostname(hass, url: str) -> str | None:
    """Read ``hostname`` (pb-pt-…) from the flat /api/system response."""
    try:
        session = async_get_clientsession(hass)
        async with session.get(
            f"{url}/api/system", timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
    except Exception:  # pragma: no cover - tests use a fake hass
        return None
    hostname = data.get("hostname") if isinstance(data, dict) else None
    return _short_hostname(str(hostname)) if _is_power_temp_hostname(hostname) else None


async def _async_power_temp_device_id(hass, url: str, hostname: str | None = None) -> str | None:
    """Prefer a pb-pt-* hostname; otherwise keep host:port from the URL."""
    if not _is_power_temp_hostname(hostname):
        hostname = await _async_fetch_power_temp_hostname(hass, url)
    if hostname:
        return _short_hostname(hostname)
    return _device_id_from_url(url) if url else None


def sensor_schema(
    name: str, offset_c: float, enabled: bool | None = None, *, removable: bool = False
) -> vol.Schema:
    """Form for one port's sensor config; shared by the options and repair flows."""
    fields = {
        vol.Optional("name", default=name): str,
        vol.Required("offset_c", default=offset_c): vol.All(
            vol.Coerce(float), vol.Range(min=OFFSET_MIN_C, max=OFFSET_MAX_C)
        ),
    }
    if enabled is not None:
        fields[vol.Required("enabled", default=enabled)] = bool
    if removable:
        fields[vol.Required("remove", default=False)] = bool
    return vol.Schema(fields)


def validate_sensor_input(user_input: dict) -> dict[str, str]:
    name = (user_input.get("name") or "").strip()
    if len(name.encode()) > SENSOR_NAME_MAX_BYTES:
        return {"name": "name_too_long"}
    return {}


def coordinator_for_entry(hass, entry_id: str):
    """The running coordinator, or None while the entry isn't loaded (e.g. device offline at startup)."""
    return (hass.data.get(DOMAIN, {}).get(entry_id) or {}).get("coordinator")


class PowerTempFlowMixin:
    """Config flow steps for adding a Powerbaas PowerTemp."""

    async def _async_zeroconf_power_temp(self, discovery_info: ZeroconfServiceInfo):
        """Handle Zeroconf discovery for pb-pt-* devices.

        Called by ``PowerbaasConfigFlow.async_step_zeroconf``; not a direct
        HA entry point since only one class in the MRO can own that step.
        """
        self.data = getattr(self, "data", {})
        hostname = (discovery_info.hostname or discovery_info.name or "").rstrip(".")
        if not _is_power_temp_hostname(hostname):
            return self.async_abort(reason="unsupported_device")

        short_hostname = _short_hostname(hostname)
        ip_address = str(discovery_info.host) if discovery_info.host else None
        device_url = f"http://{ip_address}" if ip_address else f"http://{hostname}"

        if _find_config_entry_for_device(self.hass, short_hostname):
            return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(
            config_entry_unique_id(DEVICE_TYPE_POWER_TEMP, short_hostname)
        )
        self._abort_if_unique_id_configured(updates={CONF_DEVICE_URL: device_url})

        self.data[CONF_DEVICE_URL] = device_url
        self.data[CONF_DEVICE_ID] = short_hostname
        self.context["title_placeholders"] = {"name": f"Powerbaas PowerTemp ({short_hostname})"}

        return await self.async_step_power_temp()

    async def async_step_power_temp(self, user_input=None):
        """Handle the initial step for adding a Powerbaas PowerTemp."""
        self.data = getattr(self, "data", {})
        self.data[CONF_DEVICE_TYPE] = DEVICE_TYPE_POWER_TEMP

        if user_input is not None:
            self.data.update(user_input)
            return await self.async_step_power_temp_device_config()

        schema = vol.Schema({
            vol.Required("name", default=self.data.get("name", DEFAULT_NAME)): str,
        })
        return self.async_show_form(step_id="power_temp", data_schema=schema, errors={})

    async def async_step_power_temp_device_config(self, user_input=None):
        """Handle Powerbaas PowerTemp connection configuration."""
        errors = {}
        default_url = _normalize_url(self.data.get(CONF_DEVICE_URL, ""))

        if user_input is not None:
            device_url = _normalize_url(user_input.get(CONF_DEVICE_URL, ""))

            if not device_url.startswith(("http://", "https://")):
                errors[CONF_DEVICE_URL] = "invalid_url"
            elif not await _async_test_power_temp_connection(self.hass, device_url):
                errors[CONF_DEVICE_URL] = "cannot_connect_power_temp"
            else:
                device_id = await _async_power_temp_device_id(
                    self.hass, device_url, self.data.get(CONF_DEVICE_ID)
                )
                if not device_id:
                    errors[CONF_DEVICE_URL] = "cannot_identify"
                else:
                    if _find_config_entry_for_device(self.hass, device_id):
                        return self.async_abort(reason="already_configured")

                    if self.unique_id is None:
                        await self.async_set_unique_id(
                            config_entry_unique_id(DEVICE_TYPE_POWER_TEMP, device_id)
                        )
                    self._abort_if_unique_id_configured()

                    self.data.update(
                        {CONF_DEVICE_URL: device_url, CONF_DEVICE_ID: device_id}
                    )
                    return self.async_create_entry(
                        title=self.data.get("name", DEFAULT_NAME),
                        data=self.data,
                    )

            default_url = device_url

        schema = vol.Schema({vol.Required(CONF_DEVICE_URL, default=default_url): str})
        return self.async_show_form(
            step_id="power_temp_device_config",
            data_schema=schema,
            errors=errors,
            description_placeholders={"example_url": EXAMPLE_URL},
        )


class PowerTempOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Powerbaas PowerTemp: device URL and per-port sensor config."""

    def __init__(self, config_entry):
        super().__init__()
        self._config_entry = config_entry

    async def async_step_power_temp_init(self, user_input=None):
        """Mandatory HA entry point: choose between URL and sensor settings."""
        return self.async_show_menu(
            step_id="power_temp_init",
            menu_options=["power_temp_device_config", "power_temp_sensors"],
        )

    async_step_init = async_step_power_temp_init

    async def async_step_power_temp_sensors(self, user_input=None):
        """Pick a configured sensor to edit or remove.

        Newly detected sensors aren't listed here: they're adopted via the
        "new sensor found" repair issue the coordinator raises for them.
        """
        coordinator = coordinator_for_entry(self.hass, self._config_entry.entry_id)
        if coordinator is None:
            return self.async_abort(reason="device_unavailable")

        ports = (coordinator.data or {}).get("ports") or {}
        choices = {
            str(sensor["port"]): port_label(
                sensor["port"], (ports.get(sensor["port"]) or {}).get("name") or sensor.get("name")
            )
            for sensor in (coordinator.data or {}).get("config", {}).get("sensors") or []
            if isinstance(sensor.get("port"), int)
        }
        if not choices:
            return self.async_abort(reason="no_sensors")

        if user_input is not None:
            self._port = int(user_input["port"])
            return await self.async_step_power_temp_sensor()

        return self.async_show_form(
            step_id="power_temp_sensors",
            data_schema=vol.Schema({vol.Required("port"): vol.In(choices)}),
        )

    async def async_step_power_temp_sensor(self, user_input=None):
        """Edit (or remove) one configured sensor."""
        coordinator = coordinator_for_entry(self.hass, self._config_entry.entry_id)
        if coordinator is None:
            return self.async_abort(reason="device_unavailable")

        errors = {}
        sensor = coordinator.configured_sensor(self._port) or {}
        if user_input is not None:
            errors = validate_sensor_input(user_input)
            if not errors:
                try:
                    if user_input.get("remove"):
                        await coordinator.async_remove_sensor(self._port)
                    else:
                        await coordinator.async_save_sensor(
                            self._port,
                            name=(user_input.get("name") or "").strip(),
                            offset_c=user_input["offset_c"],
                            enabled=user_input["enabled"],
                        )
                except PowerTempCommandError as err:
                    _LOGGER.warning("Saving PowerTemp port %s failed: %s", self._port, err.code)
                    errors["base"] = "cannot_save"
                else:
                    return self.async_create_entry(title="", data=dict(self._config_entry.options))
            sensor = {**sensor, **user_input}

        return self.async_show_form(
            step_id="power_temp_sensor",
            data_schema=sensor_schema(
                sensor.get("name", ""),
                sensor.get("offset_c", sensor.get("offsetC", 0.0)),
                sensor.get("enabled", True),
                removable=True,
            ),
            errors=errors,
            description_placeholders={"port": str(self._port)},
        )

    async def async_step_power_temp_device_config(self, user_input=None):
        """Ask for/update the Powerbaas PowerTemp URL."""
        errors = {}
        default_url = _normalize_url(self._config_entry.data.get(CONF_DEVICE_URL, ""))

        if user_input is not None:
            device_url = _normalize_url(user_input.get(CONF_DEVICE_URL, ""))

            if not device_url.startswith(("http://", "https://")):
                errors[CONF_DEVICE_URL] = "invalid_url"
            elif not await _async_test_power_temp_connection(self.hass, device_url):
                errors[CONF_DEVICE_URL] = "cannot_connect_power_temp"
            else:
                device_id = await _async_power_temp_device_id(
                    self.hass, device_url, self._config_entry.data.get(CONF_DEVICE_ID)
                )
                if _find_config_entry_for_device(
                    self.hass, device_id, exclude_entry_id=self._config_entry.entry_id
                ):
                    errors[CONF_DEVICE_URL] = "device_in_use"
                else:
                    new_data = dict(self._config_entry.data)
                    new_data[CONF_DEVICE_URL] = device_url
                    if device_id:
                        new_data[CONF_DEVICE_ID] = device_id
                    self.hass.config_entries.async_update_entry(
                        self._config_entry,
                        data=new_data,
                        unique_id=(
                            config_entry_unique_id(DEVICE_TYPE_POWER_TEMP, device_id)
                            if device_id
                            else self._config_entry.unique_id
                        ),
                    )
                    await self.hass.config_entries.async_reload(self._config_entry.entry_id)
                    return self.async_create_entry(title="", data={})

            default_url = device_url

        schema = vol.Schema({vol.Required(CONF_DEVICE_URL, default=default_url): str})
        return self.async_show_form(
            step_id="power_temp_device_config",
            data_schema=schema,
            errors=errors,
            description_placeholders={"example_url": EXAMPLE_URL},
        )
