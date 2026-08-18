"""Tests for AircoClient against a mocked aiohttp session (no real HTTP)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import aiohttp

from custom_components.powerbaas.devices.airco_bridge.client import AircoClient


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


def _client_with_session(session: MagicMock) -> AircoClient:
    client = object.__new__(AircoClient)
    client.hass = MagicMock()
    client.base_url = "http://airco.local"
    client._session = session
    return client


def _session_returning(response: _FakeResponse) -> MagicMock:
    session = MagicMock()
    session.get.return_value = response
    return session


async def test_async_get_status_returns_json_on_200() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(200, {"airco": {"ison": True}})))

    result = await client.async_get_status()

    assert result == {"airco": {"ison": True}}


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
        _session_returning(_FakeResponse(200, {"system": {"firmwareVersion": 9}}))
    )

    assert await client.async_get_system() == {"system": {"firmwareVersion": 9}}


async def test_async_get_types_returns_list_on_200() -> None:
    payload = {"types": [{"key": "DAIKIN", "value": 14}]}
    client = _client_with_session(_session_returning(_FakeResponse(200, payload)))

    assert await client.async_get_types() == payload["types"]


async def test_async_get_types_returns_none_on_unexpected_payload() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(200, {"nope": True})))

    assert await client.async_get_types() is None


async def test_async_control_sends_query_params() -> None:
    session = _session_returning(_FakeResponse(200, text_data="AC set to cool"))
    client = _client_with_session(session)

    ok = await client.async_control(type_id=14, mode=1, fanspeed=3, temperature=21)

    assert ok is True
    args, kwargs = session.get.call_args
    assert args[0] == "http://airco.local/control"
    assert kwargs["params"] == {"type": 14, "mode": 1, "fanspeed": 3, "temperature": 21}


async def test_async_control_off_omits_fan_and_temperature() -> None:
    session = _session_returning(_FakeResponse(200, text_data="AC turned off"))
    client = _client_with_session(session)

    ok = await client.async_control(type_id=14, mode=-1, fanspeed=3, temperature=21)

    assert ok is True
    _, kwargs = session.get.call_args
    assert kwargs["params"] == {"type": 14, "mode": -1}


async def test_async_control_false_on_failure_status() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(400, text_data="Invalid mode")))

    assert await client.async_control(type_id=14, mode=1) is False


async def test_async_test_connection_true_when_status_reachable() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(200, {"airco": {}})))

    assert await client.async_test_connection() is True


async def test_async_test_connection_false_when_unreachable() -> None:
    session = MagicMock()
    session.get.side_effect = aiohttp.ClientError("boom")
    client = _client_with_session(session)

    assert await client.async_test_connection() is False
