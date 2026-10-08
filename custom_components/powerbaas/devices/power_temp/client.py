"""Client for interacting with the Powerbaas PowerTemp firmware via HTTP API."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

API_SENSORS = "/api/sensors"
API_SYSTEM = "/api/system"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


class PowerTempClient:
    """Helper class to interact with the Powerbaas PowerTemp HTTP API."""

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
                    _LOGGER.debug("Powerbaas PowerTemp %s: %s", path, data)
                    return data if isinstance(data, dict) else None
                _LOGGER.warning(
                    "Powerbaas PowerTemp %s request failed with %s", path, response.status
                )
        except aiohttp.ClientError as err:
            _LOGGER.warning("Powerbaas PowerTemp %s request error: %s", path, err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected Powerbaas PowerTemp %s error: %s", path, err)
        return None

    async def async_get_sensors(self) -> Optional[Dict[str, Any]]:
        """Fetch overall status and per-port readings from /api/sensors."""
        return await self._async_get_json(API_SENSORS)

    async def async_get_system(self) -> Optional[Dict[str, Any]]:
        """Fetch system information from /api/system (flat object)."""
        return await self._async_get_json(API_SYSTEM)

    async def async_test_connection(self) -> bool:
        """Check whether the Powerbaas PowerTemp is reachable."""
        return await self.async_get_sensors() is not None
