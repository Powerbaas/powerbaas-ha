"""Client for interacting with the Boiler Controller firmware via HTTP API."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

# API paths
API_STATUS = "/api/status"
API_SYSTEM = "/api/system"
API_CONTROL = "/api/control"
API_CALIBRATION = "/api/calibration"
API_CALIBRATION_RUN = "/api/calibration/run"
API_CALIBRATION_STOP = "/api/calibration/stop"
API_REBOOT = "/api/reboot"


class BCClient:
    """Helper class to interact with the Boiler Controller HTTP API."""

    def __init__(self, hass: HomeAssistant, base_url: str) -> None:
        self.hass = hass
        self.base_url = base_url.rstrip("/")
        self._session = async_get_clientsession(hass)

    async def async_get_status(self) -> Optional[Dict[str, Any]]:
        """Fetch current boiler status from /api/status."""
        url = f"{self.base_url}{API_STATUS}"
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    _LOGGER.debug("BC status: %s", data)
                    return data
                _LOGGER.warning("BC status request failed with %s", response.status)
        except aiohttp.ClientError as err:
            _LOGGER.warning("BC status request error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected BC status error: %s", err)
        return None

    async def async_get_system(self) -> Optional[Dict[str, Any]]:
        """Fetch system information from /api/system."""
        url = f"{self.base_url}{API_SYSTEM}"
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    _LOGGER.debug("BC system: %s", data)
                    return data
                _LOGGER.warning("BC system request failed with %s", response.status)
        except aiohttp.ClientError as err:
            _LOGGER.warning("BC system request error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected BC system error: %s", err)
        return None

    async def async_set_heating_percentage(self, percentage: int) -> bool:
        """Set heating percentage (0–100) via POST /api/control."""
        clamped = max(0, min(100, int(percentage)))
        url = f"{self.base_url}{API_CONTROL}"
        try:
            async with self._session.post(
                url,
                json={"percentage": clamped},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    _LOGGER.debug("BC control set to %s%%", clamped)
                    return True
                body = await response.text()
                _LOGGER.warning(
                    "BC control failed with %s: %s",
                    response.status,
                    body.strip() or "<empty>",
                )
        except aiohttp.ClientError as err:
            _LOGGER.warning("BC control error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected BC control error: %s", err)
        return False

    async def async_set_target_watts(self, watts: int) -> bool:
        """Set target power in watts via POST /api/control."""
        clamped = max(0, int(watts))
        url = f"{self.base_url}{API_CONTROL}"
        try:
            async with self._session.post(
                url,
                json={"watts": clamped},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    _LOGGER.debug("BC control set to %sW", clamped)
                    return True
                body = await response.text()
                _LOGGER.warning(
                    "BC control (watts) failed with %s: %s",
                    response.status,
                    body.strip() or "<empty>",
                )
        except aiohttp.ClientError as err:
            _LOGGER.warning("BC control (watts) error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected BC control (watts) error: %s", err)
        return False

    async def async_test_connection(self) -> bool:
        """Check whether the BC device is reachable."""
        status = await self.async_get_status()
        return status is not None

    async def async_calibration_run(self) -> bool:
        """Start an automated calibration run on the device."""
        url = f"{self.base_url}{API_CALIBRATION_RUN}"
        try:
            async with self._session.post(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    return True
                body = await response.text()
                _LOGGER.warning(
                    "BC calibration/run failed with %s: %s",
                    response.status,
                    body.strip() or "<empty>",
                )
        except aiohttp.ClientError as err:
            _LOGGER.warning("BC calibration/run error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected BC calibration/run error: %s", err)
        return False

    async def async_calibration_stop(self) -> bool:
        """Request a stop of the active calibration run."""
        url = f"{self.base_url}{API_CALIBRATION_STOP}"
        try:
            async with self._session.post(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    return True
                body = await response.text()
                _LOGGER.warning(
                    "BC calibration/stop failed with %s: %s",
                    response.status,
                    body.strip() or "<empty>",
                )
        except aiohttp.ClientError as err:
            _LOGGER.warning("BC calibration/stop error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected BC calibration/stop error: %s", err)
        return False

    async def async_get_calibration(self) -> Optional[Dict[str, Any]]:
        """Fetch calibration data and run state from /api/calibration."""
        url = f"{self.base_url}{API_CALIBRATION}"
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    _LOGGER.debug("BC calibration: %s", data)
                    return data
                _LOGGER.warning(
                    "BC calibration request failed with %s", response.status
                )
        except aiohttp.ClientError as err:
            _LOGGER.warning("BC calibration request error: %s", err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected BC calibration error: %s", err)
        return None
