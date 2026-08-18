"""Config flow steps for the Powerbaas RGB device type."""
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
    DEVICE_TYPE_RGB,
    config_entry_unique_id,
)
from .const import RGB_HOST_PREFIX, CONF_DEVICE_ID, CONF_DEVICE_URL, DEFAULT_NAME

_LOGGER = logging.getLogger(__name__)


def _find_config_entry_for_device(hass, device_id: str | None, *, exclude_entry_id: str | None = None):
    """Return an existing entry that already manages this Powerbaas RGB."""
    if not device_id:
        return None

    normalized = device_id.lower()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if exclude_entry_id and entry.entry_id == exclude_entry_id:
            continue
        if entry.data.get(CONF_DEVICE_TYPE) != DEVICE_TYPE_RGB:
            continue
        entry_device_id = entry.data.get(CONF_DEVICE_ID)
        if entry_device_id and entry_device_id.lower() == normalized:
            return entry
        unique_id = (entry.unique_id or "").lower()
        if unique_id in (normalized, config_entry_unique_id(DEVICE_TYPE_RGB, normalized)):
            return entry

    return None


def _short_hostname(hostname: str) -> str:
    return hostname.rstrip(".").split(".")[0].lower()


def _device_id_from_url(url: str) -> str | None:
    """Stable id from a URL; include non-default ports so two proxies on the same host differ."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    if parsed.port and parsed.port not in (80, 443):
        return f"{host}:{parsed.port}"
    return host


class RgbFlowMixin:
    """Config flow steps for adding an Powerbaas RGB."""

    def _normalize_url(self, url: str) -> str:
        return url.strip().rstrip("/") if url else url

    async def _test_rgb_connection(self, url: str) -> bool:
        """Test connectivity by calling /api/status."""
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                f"{url}/api/status", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                return resp.status == 200
        except aiohttp.ClientError as err:
            _LOGGER.warning("Powerbaas RGB connection error: %s", err)
        except Exception as err:  # pragma: no cover
            _LOGGER.error("Unexpected Powerbaas RGB test error: %s", err)
        return False

    def _rgb_id_from_hostname_or_url(self, url: str, hostname: str | None = None) -> str | None:
        """Prefer a pb-rgb-* hostname; otherwise keep host:port from the URL.

        Named uniquely so Boiler Controller's ``_derive_device_id`` (which
        strips ports) cannot win on the shared ConfigFlow MRO.
        """
        if hostname:
            short = _short_hostname(hostname)
            if short and any(short.startswith(prefix) for prefix in RGB_HOST_PREFIX):
                return short
        return _device_id_from_url(url) if url else None

    async def _async_fetch_rgb_system_hostname(self, url: str) -> str | None:
        """Read ``system.hostname`` (pb-rgb-…) when the firmware exposes it."""
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                f"{url}/api/system", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
        except Exception:  # pragma: no cover - tests use a fake hass
            return None
        hostname = (data.get("system") or {}).get("hostname") if isinstance(data, dict) else None
        if not hostname:
            return None
        short = _short_hostname(str(hostname))
        if any(short.startswith(prefix) for prefix in RGB_HOST_PREFIX):
            return short
        return None

    async def _async_rgb_device_id_for_url(self, url: str, hostname: str | None = None) -> str | None:
        if hostname and any(_short_hostname(hostname).startswith(p) for p in RGB_HOST_PREFIX):
            return self._rgb_id_from_hostname_or_url(url, hostname)
        system_hostname = await self._async_fetch_rgb_system_hostname(url)
        return self._rgb_id_from_hostname_or_url(url, system_hostname)

    async def _async_zeroconf_rgb(self, discovery_info: ZeroconfServiceInfo):
        """Handle Zeroconf discovery for pb-rgb-* rings.

        Called by ``PowerbaasConfigFlow.async_step_zeroconf`` after it
        determines the discovered hostname belongs to an Powerbaas RGB;
        not a direct HA entry point itself since only one class in the
        flow's MRO can own ``async_step_zeroconf``.
        """
        self.data = getattr(self, "data", {})
        hostname = discovery_info.hostname or discovery_info.name
        if not hostname:
            return self.async_abort(reason="unsupported_device")

        hostname = hostname.rstrip(".")
        short_hostname = hostname.split(".")[0].lower()
        if not any(short_hostname.startswith(prefix) for prefix in RGB_HOST_PREFIX):
            return self.async_abort(reason="unsupported_device")

        ip_address = str(discovery_info.host) if discovery_info.host else None
        device_url = f"http://{ip_address}" if ip_address else f"http://{hostname}"
        device_id = short_hostname

        existing_entry = _find_config_entry_for_device(self.hass, device_id)
        if existing_entry:
            return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(config_entry_unique_id(DEVICE_TYPE_RGB, device_id))
        self._abort_if_unique_id_configured(updates={CONF_DEVICE_URL: device_url})

        self.data[CONF_DEVICE_URL] = device_url
        self.data[CONF_DEVICE_ID] = device_id
        self.context["title_placeholders"] = {"name": f"Powerbaas RGB ({short_hostname})"}

        return await self.async_step_rgb()

    async def async_step_rgb(self, user_input=None):
        """Handle the initial step for adding an Powerbaas RGB."""
        self.data = getattr(self, "data", {})
        self.data[CONF_DEVICE_TYPE] = DEVICE_TYPE_RGB
        errors = {}

        if user_input is not None:
            self.data.update(user_input)
            return await self.async_step_rgb_device_config()

        schema = vol.Schema({
            vol.Required("name", default=self.data.get("name", DEFAULT_NAME)): str,
        })
        return self.async_show_form(step_id="rgb", data_schema=schema, errors=errors)

    async def async_step_rgb_device_config(self, user_input=None):
        """Handle Powerbaas RGB connection configuration."""
        errors = {}
        stored_url = self.data.get(CONF_DEVICE_URL, "")
        default_url = self._normalize_url(stored_url)

        if user_input is not None:
            device_url = self._normalize_url(user_input.get(CONF_DEVICE_URL, ""))

            if not device_url.startswith(("http://", "https://")):
                errors[CONF_DEVICE_URL] = "invalid_url"
            elif not await self._test_rgb_connection(device_url):
                errors[CONF_DEVICE_URL] = "cannot_connect_rgb"
            else:
                device_id = await self._async_rgb_device_id_for_url(
                    device_url, self.data.get(CONF_DEVICE_ID)
                )
                if not device_id:
                    errors[CONF_DEVICE_URL] = "cannot_identify"
                else:
                    existing_entry = _find_config_entry_for_device(self.hass, device_id)
                    if existing_entry:
                        return self.async_abort(reason="already_configured")

                    unique_id = config_entry_unique_id(DEVICE_TYPE_RGB, device_id)
                    if self.unique_id is None:
                        await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                    self.data.update(
                        {CONF_DEVICE_URL: device_url, CONF_DEVICE_ID: device_id}
                    )
                    return self.async_create_entry(
                        title=self.data.get("name", DEFAULT_NAME),
                        data=self.data,
                    )

            default_url = device_url

        schema = vol.Schema({
            vol.Required(CONF_DEVICE_URL, default=default_url): str
        })
        return self.async_show_form(
            step_id="rgb_device_config",
            data_schema=schema,
            errors=errors,
            description_placeholders={"example_url": "http://pb-rgb-xxxx.local"},
        )


class RgbOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Powerbaas RGB.

    The entry-point method must be named ``async_step_init`` (Home Assistant
    calls it by that fixed name), but the step_id used for the first form is
    namespaced as "rgb_init" so it doesn't collide with other Powerbaas
    device types sharing this domain's options flow.
    """

    def __init__(self, config_entry):
        super().__init__()
        self._config_entry = config_entry

    async def async_step_rgb_init(self, user_input=None):
        """Mandatory HA entry point; has no form of its own."""
        return await self.async_step_rgb_device_config(user_input)

    async_step_init = async_step_rgb_init

    def _normalize_url(self, url: str) -> str:
        return url.strip().rstrip("/") if url else url

    async def _test_rgb_connection(self, url: str) -> bool:
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                f"{url}/api/status", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                return resp.status == 200
        except aiohttp.ClientError as err:
            _LOGGER.warning("Powerbaas RGB connection error: %s", err)
        except Exception as err:  # pragma: no cover
            _LOGGER.error("Unexpected Powerbaas RGB test error: %s", err)
        return False

    def _rgb_id_from_hostname_or_url(self, url: str, hostname: str | None = None) -> str | None:
        if hostname:
            short = _short_hostname(hostname)
            if short and any(short.startswith(prefix) for prefix in RGB_HOST_PREFIX):
                return short
        return _device_id_from_url(url) if url else None

    async def _async_fetch_rgb_system_hostname(self, url: str) -> str | None:
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                f"{url}/api/system", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
        except Exception:  # pragma: no cover - tests use a fake hass
            return None
        hostname = (data.get("system") or {}).get("hostname") if isinstance(data, dict) else None
        if not hostname:
            return None
        short = _short_hostname(str(hostname))
        if any(short.startswith(prefix) for prefix in RGB_HOST_PREFIX):
            return short
        return None

    async def _async_rgb_device_id_for_url(self, url: str, hostname: str | None = None) -> str | None:
        if hostname and any(_short_hostname(hostname).startswith(p) for p in RGB_HOST_PREFIX):
            return self._rgb_id_from_hostname_or_url(url, hostname)
        system_hostname = await self._async_fetch_rgb_system_hostname(url)
        return self._rgb_id_from_hostname_or_url(url, system_hostname)

    async def async_step_rgb_device_config(self, user_input=None):
        """Ask for/update the Powerbaas RGB URL."""
        errors = {}
        default_url = self._normalize_url(self._config_entry.data.get(CONF_DEVICE_URL, ""))

        if user_input is not None:
            device_url = self._normalize_url(user_input.get(CONF_DEVICE_URL, ""))

            if not device_url.startswith(("http://", "https://")):
                errors[CONF_DEVICE_URL] = "invalid_url"
            elif not await self._test_rgb_connection(device_url):
                errors[CONF_DEVICE_URL] = "cannot_connect_rgb"
            else:
                device_id = await self._async_rgb_device_id_for_url(
                    device_url, self._config_entry.data.get(CONF_DEVICE_ID)
                )
                existing_entry = _find_config_entry_for_device(
                    self.hass, device_id, exclude_entry_id=self._config_entry.entry_id
                )
                if existing_entry:
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
                            config_entry_unique_id(DEVICE_TYPE_RGB, device_id)
                            if device_id
                            else self._config_entry.unique_id
                        ),
                    )
                    await self.hass.config_entries.async_reload(self._config_entry.entry_id)
                    return self.async_create_entry(title="", data={})

            default_url = device_url

        schema = vol.Schema({vol.Required(CONF_DEVICE_URL, default=default_url): str})
        return self.async_show_form(
            step_id="rgb_device_config",
            data_schema=schema,
            errors=errors,
            description_placeholders={"example_url": "http://pb-rgb-xxxx.local"},
        )
