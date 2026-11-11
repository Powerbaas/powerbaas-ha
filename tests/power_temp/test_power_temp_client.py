"""POST /api/config: success, firmware rejection codes and connection errors."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest

from custom_components.powerbaas.devices.power_temp.client import (
    PowerTempClient,
    PowerTempCommandError,
)


class _FakeResponse:
    def __init__(self, json_data: Any, status: int) -> None:
        self.status = status
        self._json_data = json_data

    async def json(self, content_type=None):  # noqa: ANN001
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return False


class _FakeSession:
    def __init__(self, response: _FakeResponse | None = None, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc
        self.posted: list[tuple[str, Any]] = []

    def post(self, url: str, json=None, timeout=None):  # noqa: ANN001
        self.posted.append((url, json))
        if self._exc is not None:
            raise self._exc
        return self._response


def _client(monkeypatch: pytest.MonkeyPatch, session: _FakeSession) -> PowerTempClient:
    monkeypatch.setattr(
        "custom_components.powerbaas.devices.power_temp.client.async_get_clientsession",
        lambda _hass: session,
    )
    return PowerTempClient(None, "http://pt.local/")


async def test_update_config_returns_new_config(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(_FakeResponse({"thresholds": {"warnC": 50}}, 200))

    result = await _client(monkeypatch, session).async_update_config({"thresholds": {"warnC": 50}})

    assert result == {"thresholds": {"warnC": 50}}
    assert session.posted == [("http://pt.local/api/config", {"thresholds": {"warnC": 50}})]


async def test_update_config_raises_firmware_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(_FakeResponse({"error": "multiple_ambient"}, 400))

    with pytest.raises(PowerTempCommandError) as exc_info:
        await _client(monkeypatch, session).async_update_config({"sensors": []})

    assert exc_info.value.code == "multiple_ambient"


async def test_update_config_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(exc=aiohttp.ClientError("boom"))

    with pytest.raises(PowerTempCommandError) as exc_info:
        await _client(monkeypatch, session).async_update_config({})

    assert exc_info.value.code == "cannot_connect"
