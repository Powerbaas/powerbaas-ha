"""Serve solar data from Home Assistant to the P1 meter's custom solar integration.

The P1 firmware can poll an HTTP URL for solar production, expecting
``{"current": <W>, "total": <Wh>}``. When enabled for a P1 entry, this
registers a local-only, GET-only Home Assistant webhook that builds that JSON
from two HA sensors the user picked (a power sensor and an energy sensor),
converted to W and Wh whatever unit they report in.

The webhook id is a random token stored in the config entry: the URL needs no
login, so knowing the URL is what grants access. ``local_only`` makes HA's
webhook component drop requests that don't come from the local network
(including Nabu Casa cloud), it answers those with an empty 200.
"""
from __future__ import annotations

import logging
import secrets
from http import HTTPStatus

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.network import NoURLAvailableError
from homeassistant.util.unit_conversion import EnergyConverter, PowerConverter

from ...const import DOMAIN
from .const import (
    CONF_SOLAR_ENERGY_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    CONF_SOLAR_PUSH_ENABLED,
    CONF_SOLAR_WEBHOOK_ID,
    P1_SOLAR_UNIQUE_ID_SUFFIXES,
)

_LOGGER = logging.getLogger(__name__)

# Shown in the URL when Home Assistant doesn't know its own local address
# (no internal URL configured and no local IP found).
FALLBACK_BASE_URL = "http://<home-assistant-ip>:8123"


def generate_webhook_id() -> str:
    """A random webhook id for the solar URL.

    16 bytes (32 hex chars) instead of webhook.async_generate_id()'s 32 bytes,
    to keep the URL short enough for the P1 firmware's URL field. 128 bits is
    still far beyond guessable.
    """
    return secrets.token_hex(16)


def solar_push_url(hass: HomeAssistant, webhook_id: str) -> str:
    """The local URL the P1 should poll (the P1 is on the LAN, so never the external/cloud URL)."""
    try:
        return webhook.async_generate_url(
            hass, webhook_id, allow_external=False, prefer_external=False
        )
    except NoURLAvailableError:
        return f"{FALLBACK_BASE_URL}{webhook.async_generate_path(webhook_id)}"


def own_solar_entity_ids(hass: HomeAssistant) -> list[str]:
    """Entity ids of every Powerbaas P1's own Solar sensors, to keep out of the source pickers."""
    registry = er.async_get(hass)
    return [
        reg_entry.entity_id
        for reg_entry in registry.entities.values()
        if reg_entry.platform == DOMAIN
        and reg_entry.unique_id.endswith(P1_SOLAR_UNIQUE_ID_SUFFIXES)
    ]


def _read_converted(hass: HomeAssistant, entity_id: str, converter, target_unit: str) -> float | None:
    """The entity's state converted to target_unit, or None if missing/unavailable/unconvertible."""
    state = hass.states.get(entity_id)
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    try:
        value = float(state.state)
    except ValueError:
        return None

    unit = state.attributes.get("unit_of_measurement")
    if unit not in converter.VALID_UNITS:
        return None
    return converter.convert(value, unit, target_unit)


def build_payload(hass: HomeAssistant, power_entity: str, energy_entity: str) -> dict | None:
    """``{"current": W, "total": Wh}`` from the two source sensors, or None if either can't be read.

    Both values are required: a made-up 0 would show as "no production" on
    the P1, and a total of 0 would break its total-increasing statistics.
    """
    current = _read_converted(hass, power_entity, PowerConverter, UnitOfPower.WATT)
    total = _read_converted(hass, energy_entity, EnergyConverter, UnitOfEnergy.WATT_HOUR)
    if current is None or total is None:
        return None
    return {"current": round(current), "total": round(total)}


def unit_is_valid(hass: HomeAssistant, entity_id: str, converter) -> bool:
    """False only if the entity reports a unit the converter can't handle.

    An entity without state/unit right now (e.g. unavailable at startup)
    passes - the webhook answers 503 until it reports a value.
    """
    state = hass.states.get(entity_id)
    if state is None:
        return True
    unit = state.attributes.get("unit_of_measurement")
    return unit is None or unit in converter.VALID_UNITS


def async_register(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the solar webhook for this P1 entry, if enabled."""
    data = entry.data
    if not data.get(CONF_SOLAR_PUSH_ENABLED):
        return
    webhook_id = data.get(CONF_SOLAR_WEBHOOK_ID)
    power_entity = data.get(CONF_SOLAR_POWER_ENTITY)
    energy_entity = data.get(CONF_SOLAR_ENERGY_ENTITY)
    if not (webhook_id and power_entity and energy_entity):
        _LOGGER.warning("Solar for the P1 is enabled but not fully configured, skipping")
        return

    async def _handle(hass: HomeAssistant, _webhook_id: str, _request) -> web.Response:
        payload = build_payload(hass, power_entity, energy_entity)
        if payload is None:
            return web.Response(status=HTTPStatus.SERVICE_UNAVAILABLE)
        return web.json_response(payload)

    webhook.async_register(
        hass,
        DOMAIN,
        f"{entry.title or 'Powerbaas'} solar",
        webhook_id,
        _handle,
        local_only=True,
        allowed_methods=["GET"],
    )


def async_unregister(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove this entry's solar webhook (no-op if it was never registered)."""
    webhook_id = entry.data.get(CONF_SOLAR_WEBHOOK_ID)
    if webhook_id:
        webhook.async_unregister(hass, webhook_id)
