"""Tests for BCClient against a mocked aiohttp session (no real HTTP)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import aiohttp

from custom_components.powerbaas.devices.boiler_controller.bc_client import BCClient


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


def _client_with_session(session: MagicMock) -> BCClient:
    client = object.__new__(BCClient)
    client.hass = MagicMock()
    client.base_url = "http://bc.local"
    client._session = session
    return client


def _session_returning(response: _FakeResponse) -> MagicMock:
    session = MagicMock()
    session.get.return_value = response
    session.post.return_value = response
    return session


async def test_async_get_status_returns_json_on_200() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(200, {"power": 500})))

    result = await client.async_get_status()

    assert result == {"power": 500}


async def test_async_get_status_returns_none_on_non_200() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(500)))

    assert await client.async_get_status() is None


async def test_async_get_status_returns_none_on_client_error() -> None:
    session = MagicMock()
    session.get.side_effect = aiohttp.ClientError("boom")
    client = _client_with_session(session)

    assert await client.async_get_status() is None


async def test_async_set_heating_percentage_clamps_and_posts() -> None:
    session = _session_returning(_FakeResponse(200))
    client = _client_with_session(session)

    ok = await client.async_set_heating_percentage(150)

    assert ok is True
    _, kwargs = session.post.call_args
    assert kwargs["json"] == {"percentage": 100}


async def test_async_set_heating_percentage_false_on_failure_status() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(500, text_data="nope")))

    assert await client.async_set_heating_percentage(50) is False


async def test_async_set_target_watts_clamps_negative_to_zero() -> None:
    session = _session_returning(_FakeResponse(200))
    client = _client_with_session(session)

    ok = await client.async_set_target_watts(-10)

    assert ok is True
    _, kwargs = session.post.call_args
    assert kwargs["json"] == {"watts": 0}


async def test_async_set_ssr_returns_reported_state() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(200, {"on": True})))

    assert await client.async_set_ssr(True) is True


async def test_async_set_ssr_returns_none_on_failure() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(500)))

    assert await client.async_set_ssr(True) is None


async def test_async_test_connection_true_when_status_reachable() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(200, {"power": 0})))

    assert await client.async_test_connection() is True


async def test_async_test_connection_false_when_unreachable() -> None:
    session = MagicMock()
    session.get.side_effect = aiohttp.ClientError("boom")
    client = _client_with_session(session)

    assert await client.async_test_connection() is False


async def test_async_calibration_run_true_on_200() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(200)))

    assert await client.async_calibration_run() is True


async def test_async_calibration_run_false_on_failure() -> None:
    client = _client_with_session(_session_returning(_FakeResponse(500)))

    assert await client.async_calibration_run() is False


async def test_async_get_calibration_returns_data_on_200() -> None:
    client = _client_with_session(
        _session_returning(_FakeResponse(200, {"run": {"state": "running"}}))
    )

    assert await client.async_get_calibration() == {"run": {"state": "running"}}
