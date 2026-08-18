"""Tests for RgbClient against a mocked aiohttp session (no real HTTP)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import aiohttp

from custom_components.powerbaas.devices.rgb.client import RgbClient


class _FakeResponse:
    def __init__(self, status: int = 200, json_data: Any = None, text_data: str = "") -> None:
        self.status = status
        self._json_data = json_data
        self._text_data = text_data

    async def json(self, content_type=None):  # noqa: ANN001
        return self._json_data

    async def text(self):
        return self._text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


def _client_with_session(session: MagicMock) -> RgbClient:
    client = object.__new__(RgbClient)
    client.hass = MagicMock()
    client.base_url = "http://rgb.local"
    client._session = session
    return client


def _session_returning(response: _FakeResponse) -> MagicMock:
    session = MagicMock()
    session.get.return_value = response
    return session


async def test_async_get_status_returns_json_on_200() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(200, {"rgb": {"ison": True}})))

    result = await client.async_get_status()

    assert result == {"rgb": {"ison": True}}


async def test_async_get_status_returns_none_on_non_200() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(500)))

    assert await client.async_get_status() is None


async def test_async_get_status_returns_none_on_client_error() -> None:
    session = MagicMock()
    session.get.side_effect = aiohttp.ClientError("boom")
    client = _client_with_session(session)

    assert await client.async_get_status() is None


async def test_async_get_system_returns_json_on_200() -> None:
    client = _client_with_session(
        _session_returning(_FakeResponse(200, {"system": {"firmwareVersion": 1}}))
    )

    assert await client.async_get_system() == {"system": {"firmwareVersion": 1}}


async def test_async_set_rgb_sends_query_params() -> None:
    session = _session_returning(_FakeResponse(200, text_data="OK"))
    client = _client_with_session(session)

    ok = await client.async_set_rgb(on=1, brightness=128, r=255, g=0, b=0, effect="solid")

    assert ok is True
    args, kwargs = session.get.call_args
    assert args[0] == "http://rgb.local/api/rgb"
    assert kwargs["params"] == {
        "on": 1,
        "brightness": 128,
        "r": 255,
        "g": 0,
        "b": 0,
        "effect": "solid",
    }


async def test_async_set_rgb_false_on_failure_status() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(400, text_data="bad")))

    assert await client.async_set_rgb(on=0) is False


async def test_async_set_mode_sends_query_param() -> None:
    session = _session_returning(_FakeResponse(200, text_data="OK"))
    client = _client_with_session(session)

    ok = await client.async_set_mode("Standalone")

    assert ok is True
    args, kwargs = session.get.call_args
    assert args[0] == "http://rgb.local/api/mode/update"
    assert kwargs["params"] == {"mode": "Standalone"}


async def test_async_test_connection_true_when_status_reachable() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(200, {"rgb": {}})))

    assert await client.async_test_connection() is True


async def test_async_test_connection_false_when_unreachable() -> None:
    session = MagicMock()
    session.get.side_effect = aiohttp.ClientError("boom")
    client = _client_with_session(session)

    assert await client.async_test_connection() is False
