"""Config flow steps for the P1 meter device type."""
import logging
from urllib.parse import urlparse

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.util.unit_conversion import EnergyConverter, PowerConverter

from ...const import DOMAIN, CONF_DEVICE_TYPE, DEVICE_TYPE_P1_METER
from . import solar_push
from .const import (
    CONF_SOLAR_ENERGY_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    CONF_SOLAR_PUSH_ENABLED,
    CONF_SOLAR_WEBHOOK_ID,
    DEFAULT_SCAN_INTERVAL,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

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


def _solar_source_selector(hass, device_class: str) -> selector.EntitySelector:
    config = {"domain": "sensor", "device_class": device_class}
    own = solar_push.own_solar_entity_ids(hass)
    if own:
        config["exclude_entities"] = own
    return selector.EntitySelector(selector.EntitySelectorConfig(**config))


def _solar_schema(hass, data: dict) -> vol.Schema:
    """Both source sensors, prefilled from data when already chosen."""

    def _required(key):
        if data.get(key):
            return vol.Required(key, default=data[key])
        return vol.Required(key)

    return vol.Schema({
        _required(CONF_SOLAR_POWER_ENTITY): _solar_source_selector(hass, "power"),
        _required(CONF_SOLAR_ENERGY_ENTITY): _solar_source_selector(hass, "energy"),
    })


def _validate_solar(hass, user_input: dict) -> dict:
    errors = {}
    if not solar_push.unit_is_valid(hass, user_input[CONF_SOLAR_POWER_ENTITY], PowerConverter):
        errors[CONF_SOLAR_POWER_ENTITY] = "invalid_power_unit"
    if not solar_push.unit_is_valid(hass, user_input[CONF_SOLAR_ENERGY_ENTITY], EnergyConverter):
        errors[CONF_SOLAR_ENERGY_ENTITY] = "invalid_energy_unit"
    return errors


def _apply_solar(data: dict, user_input: dict) -> dict:
    """data plus the chosen sensors and a webhook id - kept if one exists, so the URL in the P1 stays valid."""
    return {
        **data,
        CONF_SOLAR_POWER_ENTITY: user_input[CONF_SOLAR_POWER_ENTITY],
        CONF_SOLAR_ENERGY_ENTITY: user_input[CONF_SOLAR_ENERGY_ENTITY],
        CONF_SOLAR_WEBHOOK_ID: data.get(CONF_SOLAR_WEBHOOK_ID) or solar_push.generate_webhook_id(),
    }


def _solar_url_placeholders(hass, data: dict) -> dict:
    """The URL for the P1, plus what it would get right now (HTTP 503 if a sensor has no value)."""
    payload = solar_push.build_payload(
        hass, data[CONF_SOLAR_POWER_ENTITY], data[CONF_SOLAR_ENERGY_ENTITY]
    )
    preview = (
        f'{{"current": {payload["current"]}, "total": {payload["total"]}}}'
        if payload is not None
        else "HTTP 503"
    )
    return {
        "url": solar_push.solar_push_url(hass, data[CONF_SOLAR_WEBHOOK_ID]),
        "preview": preview,
    }


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
                user_input[CONF_SOLAR_PUSH_ENABLED] = bool(user_input.get(CONF_SOLAR_PUSH_ENABLED))
                if user_input[CONF_SOLAR_PUSH_ENABLED]:
                    self._p1_entry_data = user_input
                    return await self.async_step_p1_meter_solar()
                return self.async_create_entry(title=name, data=user_input)

        schema = vol.Schema({
            vol.Required("host", default=self.data.get("host", DEFAULT_HOST)): str,
            vol.Optional("name", default=DEFAULT_NAME): str,
            vol.Required("scan_interval", default=DEFAULT_SCAN_INTERVAL): SCAN_INTERVAL_SCHEMA,
            vol.Optional(CONF_SOLAR_PUSH_ENABLED, default=False): bool,
        })

        return self.async_show_form(step_id="p1_meter", data_schema=schema, errors=errors)

    async def async_step_p1_meter_solar(self, user_input=None):
        """Pick the HA sensors the P1 gets its solar data from."""
        errors = {}
        if user_input is not None:
            errors = _validate_solar(self.hass, user_input)
            if not errors:
                self._p1_entry_data = _apply_solar(self._p1_entry_data, user_input)
                return await self.async_step_p1_meter_solar_url()

        return self.async_show_form(
            step_id="p1_meter_solar",
            data_schema=_solar_schema(self.hass, user_input or self._p1_entry_data),
            errors=errors,
        )

    async def async_step_p1_meter_solar_url(self, user_input=None):
        """Show the URL to enter in the P1, then create the entry."""
        data = self._p1_entry_data
        if user_input is not None:
            return self.async_create_entry(title=data["name"], data=data)

        return self.async_show_form(
            step_id="p1_meter_solar_url",
            data_schema=vol.Schema({}),
            description_placeholders=_solar_url_placeholders(self.hass, data),
        )


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
                new_data[CONF_SOLAR_PUSH_ENABLED] = bool(user_input.get(CONF_SOLAR_PUSH_ENABLED))

                if new_data[CONF_SOLAR_PUSH_ENABLED]:
                    self._new_data = new_data
                    return await self.async_step_p1_meter_solar()
                return await self._async_save(new_data)

        schema = vol.Schema({
            vol.Required("host", default=self.config_entry.data.get("host", DEFAULT_HOST)): str,
            vol.Required(
                "scan_interval",
                default=self.config_entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL),
            ): SCAN_INTERVAL_SCHEMA,
            vol.Optional(
                CONF_SOLAR_PUSH_ENABLED,
                default=self.config_entry.data.get(CONF_SOLAR_PUSH_ENABLED, False),
            ): bool,
        })

        return self.async_show_form(step_id="p1_meter_init", data_schema=schema, errors=errors)

    async_step_init = async_step_p1_meter_init

    async def async_step_p1_meter_solar(self, user_input=None):
        """Pick the HA sensors the P1 gets its solar data from."""
        errors = {}
        if user_input is not None:
            errors = _validate_solar(self.hass, user_input)
            if not errors:
                self._new_data = _apply_solar(self._new_data, user_input)
                return await self.async_step_p1_meter_solar_url()

        return self.async_show_form(
            step_id="p1_meter_solar",
            data_schema=_solar_schema(self.hass, user_input or self._new_data),
            errors=errors,
        )

    async def async_step_p1_meter_solar_url(self, user_input=None):
        """Show the URL to enter in the P1, then save and reload."""
        if user_input is not None:
            return await self._async_save(self._new_data)

        return self.async_show_form(
            step_id="p1_meter_solar_url",
            data_schema=vol.Schema({}),
            description_placeholders=_solar_url_placeholders(self.hass, self._new_data),
        )

    async def _async_save(self, new_data: dict):
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)
        return self.async_create_entry(title="", data={})
