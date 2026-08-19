"""Client for interacting with the Powerbaas RGB firmware via HTTP API."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

API_STATUS = "/api/status"
API_SYSTEM = "/api/system"
API_RGB = "/api/rgb"
API_MODE_UPDATE = "/api/mode/update"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


class RgbClient:
    """Helper class to interact with the Powerbaas RGB HTTP API."""

    def __init__(self, hass: HomeAssistant, base_url: str) -> None:
        self.hass = hass
        self.base_url = base_url.rstrip("/")
        self._session = async_get_clientsession(hass)

    async def async_get_status(self) -> Optional[Dict[str, Any]]:
        """Fetch current RGB state from /api/status."""
        url = f"{self.base_url}{API_STATUS}"
        try:
            async with self._session.get(url, timeout=REQUEST_TIMEOUT) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    _LOGGER.debug("Powerbaas RGB status: %s", data)
                    return data
                _LOGGER.warning("Powerbaas RGB status request failed with %s", response.status)
        except aiohttp.ClientError as err:
            _LOGGER.warning("Powerbaas RGB status request error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected Powerbaas RGB status error: %s", err)
        return None

    async def async_get_system(self) -> Optional[Dict[str, Any]]:
        """Fetch system information from /api/system."""
        url = f"{self.base_url}{API_SYSTEM}"
        try:
            async with self._session.get(url, timeout=REQUEST_TIMEOUT) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    _LOGGER.debug("Powerbaas RGB system: %s", data)
                    return data
                _LOGGER.warning("Powerbaas RGB system request failed with %s", response.status)
        except aiohttp.ClientError as err:
            _LOGGER.warning("Powerbaas RGB system request error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected Powerbaas RGB system error: %s", err)
        return None

    async def async_set_rgb(self, **params: Any) -> bool:
        """Send RGB controls via GET /api/rgb.

        Supported query params (firmware): brightness (0-255), on (0/1),
        colorBlind (0/1). Color/r/g/b/effect only apply in Standalone mode.
        """
        url = f"{self.base_url}{API_RGB}"
        try:
            async with self._session.get(
                url, params=params, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status == 200:
                    _LOGGER.debug("Powerbaas RGB set: %s", params)
                    return True
                body = await response.text()
                _LOGGER.warning(
                    "Powerbaas RGB set failed with %s: %s",
                    response.status,
                    body.strip() or "<empty>",
                )
        except aiohttp.ClientError as err:
            _LOGGER.warning("Powerbaas RGB set error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected Powerbaas RGB set error: %s", err)
        return False

    async def async_set_mode(self, mode: str) -> bool:
        """Switch application mode via GET /api/mode/update?mode=..."""
        url = f"{self.base_url}{API_MODE_UPDATE}"
        try:
            async with self._session.get(
                url, params={"mode": mode}, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status == 200:
                    _LOGGER.debug("Powerbaas RGB mode: %s", mode)
                    return True
                body = await response.text()
                _LOGGER.warning(
                    "Powerbaas RGB mode update failed with %s: %s",
                    response.status,
                    body.strip() or "<empty>",
                )
        except aiohttp.ClientError as err:
            _LOGGER.warning("Powerbaas RGB mode update error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected Powerbaas RGB mode update error: %s", err)
        return False

    async def async_test_connection(self) -> bool:
        """Check whether the Powerbaas RGB is reachable."""
        status = await self.async_get_status()
        return status is not None
