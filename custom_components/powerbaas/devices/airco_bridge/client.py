"""Client for interacting with the Airco Bridge firmware via HTTP API."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

API_STATUS = "/api/status"
API_SYSTEM = "/api/system"
API_CONTROL = "/control"
API_TYPES = "/types"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


class AircoClient:
    """Helper class to interact with the Airco Bridge HTTP API."""

    def __init__(self, hass: HomeAssistant, base_url: str) -> None:
        self.hass = hass
        self.base_url = base_url.rstrip("/")
        self._session = async_get_clientsession(hass)

    async def async_get_status(self) -> Optional[Dict[str, Any]]:
        """Fetch current airco and temperature status from /api/status."""
        url = f"{self.base_url}{API_STATUS}"
        try:
            async with self._session.get(url, timeout=REQUEST_TIMEOUT) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    _LOGGER.debug("Airco Bridge status: %s", data)
                    return data
                _LOGGER.warning("Airco Bridge status request failed with %s", response.status)
        except aiohttp.ClientError as err:
            _LOGGER.warning("Airco Bridge status request error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected Airco Bridge status error: %s", err)
        return None

    async def async_get_system(self) -> Optional[Dict[str, Any]]:
        """Fetch system information from /api/system."""
        url = f"{self.base_url}{API_SYSTEM}"
        try:
            async with self._session.get(url, timeout=REQUEST_TIMEOUT) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    _LOGGER.debug("Airco Bridge system: %s", data)
                    return data
                _LOGGER.warning("Airco Bridge system request failed with %s", response.status)
        except aiohttp.ClientError as err:
            _LOGGER.warning("Airco Bridge system request error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected Airco Bridge system error: %s", err)
        return None

    async def async_get_types(self) -> Optional[List[Dict[str, Any]]]:
        """Fetch IR protocol types from /types."""
        url = f"{self.base_url}{API_TYPES}"
        try:
            async with self._session.get(url, timeout=REQUEST_TIMEOUT) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    types = data.get("types") if isinstance(data, dict) else None
                    if isinstance(types, list):
                        return types
                    _LOGGER.warning("Airco Bridge /types returned unexpected payload")
                    return None
                _LOGGER.warning("Airco Bridge types request failed with %s", response.status)
        except aiohttp.ClientError as err:
            _LOGGER.warning("Airco Bridge types request error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected Airco Bridge types error: %s", err)
        return None

    async def async_control(
        self,
        *,
        type_id: int,
        mode: int,
        fanspeed: int = 0,
        temperature: int = 21,
    ) -> bool:
        """Send a control command via GET /control.

        ``mode=-1`` turns the airco off; temperature and fanspeed are ignored
        by the firmware in that case but still accepted.
        """
        params: Dict[str, Any] = {"type": int(type_id), "mode": int(mode)}
        if mode != -1:
            params["fanspeed"] = int(fanspeed)
            params["temperature"] = int(temperature)

        url = f"{self.base_url}{API_CONTROL}"
        try:
            async with self._session.get(
                url, params=params, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status == 200:
                    _LOGGER.debug("Airco Bridge control: %s", params)
                    return True
                body = await response.text()
                _LOGGER.warning(
                    "Airco Bridge control failed with %s: %s",
                    response.status,
                    body.strip() or "<empty>",
                )
        except aiohttp.ClientError as err:
            _LOGGER.warning("Airco Bridge control error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected Airco Bridge control error: %s", err)
        return False

    async def async_test_connection(self) -> bool:
        """Check whether the Airco Bridge is reachable."""
        status = await self.async_get_status()
        return status is not None
