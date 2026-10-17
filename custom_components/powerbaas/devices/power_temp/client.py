"""Client for interacting with the PowerTemp firmware via HTTP API."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

API_SENSORS = "/api/sensors"
API_SYSTEM = "/api/system"
API_CONFIG = "/api/config"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


class PowerTempCommandError(Exception):
    """A config change was not applied.

    ``code`` is the firmware's ``{"error": ...}`` code (e.g.
    ``invalid_thresholds``, ``multiple_ambient``) or ``cannot_connect``.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PowerTempClient:
    """Helper class to interact with the PowerTemp HTTP API."""

    def __init__(self, hass: HomeAssistant, base_url: str) -> None:
        self.hass = hass
        self.base_url = base_url.rstrip("/")
        self._session = async_get_clientsession(hass)

    async def _async_get_json(self, path: str) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}{path}"
        try:
            async with self._session.get(url, timeout=REQUEST_TIMEOUT) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    _LOGGER.debug("PowerTemp %s: %s", path, data)
                    return data if isinstance(data, dict) else None
                _LOGGER.warning(
                    "PowerTemp %s request failed with %s", path, response.status
                )
        except aiohttp.ClientError as err:
            _LOGGER.warning("PowerTemp %s request error: %s", path, err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected PowerTemp %s error: %s", path, err)
        return None

    async def async_get_sensors(self) -> Optional[Dict[str, Any]]:
        """Fetch overall status and per-port readings from /api/sensors."""
        return await self._async_get_json(API_SENSORS)

    async def async_get_system(self) -> Optional[Dict[str, Any]]:
        """Fetch system information from /api/system (flat object)."""
        return await self._async_get_json(API_SYSTEM)

    async def async_get_config(self) -> Optional[Dict[str, Any]]:
        """Fetch thresholds, delta limits and per-port sensor config from /api/config."""
        return await self._async_get_json(API_CONFIG)

    async def async_update_config(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """POST a partial config; returns the resulting full config.

        The firmware merges top-level keys (and keys inside ``thresholds`` /
        ``delta``), but a ``sensors`` array replaces the whole sensor list.
        Raises PowerTempCommandError when the change is rejected.
        """
        url = f"{self.base_url}{API_CONFIG}"
        try:
            async with self._session.post(url, json=body, timeout=REQUEST_TIMEOUT) as response:
                data = await response.json(content_type=None)
                if response.status == 200 and isinstance(data, dict):
                    _LOGGER.debug("PowerTemp config updated: %s", body)
                    return data
                code = data.get("error") if isinstance(data, dict) else None
                _LOGGER.warning(
                    "PowerTemp config update failed with %s: %s",
                    response.status,
                    code,
                )
                raise PowerTempCommandError(code or f"http_{response.status}")
        except aiohttp.ClientError as err:
            _LOGGER.warning("PowerTemp config update error: %s", err)
            raise PowerTempCommandError("cannot_connect") from err
        except ValueError as err:
            raise PowerTempCommandError("invalid_response") from err

    async def async_test_connection(self) -> bool:
        """Check whether the PowerTemp is reachable."""
        return await self.async_get_sensors() is not None
