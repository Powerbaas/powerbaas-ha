"""Config flow steps for the P1 meter device type."""
import logging
from urllib.parse import urlparse

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from ...const import DOMAIN, CONF_DEVICE_TYPE, DEVICE_TYPE_P1_METER
from .const import DEFAULT_SCAN_INTERVAL, MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)
DEFAULT_HOST = "http://192.168.x.x"
DEFAULT_NAME = "Powerbaas"

SCAN_INTERVAL_SCHEMA = vol.All(
    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
)


def _is_valid_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


async def _test_connection(host):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(host, timeout=aiohttp.ClientTimeout(total=10)) as response:
                return response.status < 400
    except Exception as err:
        _LOGGER.debug("Connection test failed for %s: %s", host, err)
        return False


class P1MeterFlowMixin:
    """Config flow steps for adding a P1 meter."""

    async def _async_zeroconf_p1_meter(self, discovery_info: ZeroconfServiceInfo):
        """Handle Zeroconf discovery of the P1 meter.

        Called by ``PowerbaasConfigFlow.async_step_zeroconf`` after it
        determines the discovered hostname is the P1 meter's fixed
        "powerbaas.local" name. Every P1 meter announces the same hostname,
        so (unlike the Boiler Controller) only one P1 meter per installation
        is supported - a second discovery simply aborts as already configured.
        """
        self.data = getattr(self, "data", {})

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_P1_METER) == DEVICE_TYPE_P1_METER:
                return self.async_abort(reason="p1_already_configured")

        ip_address = str(discovery_info.host) if discovery_info.host else None
        if not ip_address:
            return self.async_abort(reason="unsupported_device")

        await self.async_set_unique_id(DEVICE_TYPE_P1_METER)
        self._abort_if_unique_id_configured()

        self.data["host"] = f"http://{ip_address}"
        self.context["title_placeholders"] = {"name": f"P1 Meter ({ip_address})"}

        return await self.async_step_p1_meter()

    async def async_step_p1_meter(self, user_input=None):
        errors = {}
        self.data = getattr(self, "data", {})

        if user_input is not None:
            host = user_input["host"].rstrip("/")
            name = user_input.get("name") or DEFAULT_NAME

            if not _is_valid_url(host):
                errors["host"] = "invalid_host"
            elif not await _test_connection(host):
                errors["host"] = "cannot_connect"
            else:
                user_input["host"] = host
                user_input["name"] = name
                user_input[CONF_DEVICE_TYPE] = DEVICE_TYPE_P1_METER
                return self.async_create_entry(title=name, data=user_input)

        schema = vol.Schema({
            vol.Required("host", default=self.data.get("host", DEFAULT_HOST)): str,
            vol.Optional("name", default=DEFAULT_NAME): str,
            vol.Required("scan_interval", default=DEFAULT_SCAN_INTERVAL): SCAN_INTERVAL_SCHEMA,
        })

        return self.async_show_form(step_id="p1_meter", data_schema=schema, errors=errors)


class P1MeterOptionsFlow(config_entries.OptionsFlow):
    """Options flow for an existing P1 meter entry.

    The entry-point method must be named ``async_step_init`` (Home Assistant
    calls it by that fixed name), but the step_id used for the form/translation
    lookup is namespaced as "p1_meter_init" so it doesn't collide with other
    Powerbaas device types sharing this domain's options flow.
    """

    async def async_step_p1_meter_init(self, user_input=None):
        errors = {}

        if user_input is not None:
            host = user_input["host"].rstrip("/")

            if not _is_valid_url(host):
                errors["host"] = "invalid_host"
            elif not await _test_connection(host):
                errors["host"] = "cannot_connect"
            else:
                new_data = dict(self.config_entry.data)
                new_data["host"] = host
                new_data["scan_interval"] = user_input["scan_interval"]

                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                return self.async_create_entry(title="", data={})

        schema = vol.Schema({
            vol.Required("host", default=self.config_entry.data.get("host", DEFAULT_HOST)): str,
            vol.Required(
                "scan_interval",
                default=self.config_entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL),
            ): SCAN_INTERVAL_SCHEMA,
        })

        return self.async_show_form(step_id="p1_meter_init", data_schema=schema, errors=errors)

    async_step_init = async_step_p1_meter_init
