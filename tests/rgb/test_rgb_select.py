"""Application mode select command mapping against a fake coordinator/client."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.powerbaas.devices.rgb.select import RgbModeSelect


def _select(*, system: dict, rgb: dict | None = None, online: bool = True) -> RgbModeSelect:
    client = SimpleNamespace(async_set_mode=AsyncMock(return_value=True))
    coordinator = SimpleNamespace(
        data={"rgb": rgb or {}, "system": system},
        device_online=online,
        device_name="Powerbaas RGB",
        device_url="http://rgb.local",
        client=client,
        async_request_refresh=AsyncMock(),
    )
    coordinator.async_set_updated_data = MagicMock(
        side_effect=lambda data: setattr(coordinator, "data", data)
    )
    entry = MagicMock()
    entry.entry_id = "rgb_entry"
    select = object.__new__(RgbModeSelect)
    select.coordinator = coordinator
    select._entry = entry
    select._attr_unique_id = "rgb_entry_application_mode"
    select._attr_device_info = {}
    select._command_seq = 0
    return select


async def test_select_option_sends_mode() -> None:
    select = _select(system={"mode": "Powerbaas"})

    await RgbModeSelect.async_select_option(select, "Standalone")

    select.coordinator.client.async_set_mode.assert_awaited_once_with("Standalone")


# Regression test for the toggle-flicker bug (see test_rgb_light.py): a
# refresh right after the command can race the firmware and read back the
# stale pre-command mode. The fix updates coordinator.data optimistically.


async def test_select_option_reflects_immediately_without_refetch() -> None:
    select = _select(system={"mode": "Powerbaas", "firmwareVersion": "1.0"})

    await RgbModeSelect.async_select_option(select, "Standalone")

    assert RgbModeSelect.current_option.fget(select) == "Standalone"
    select.coordinator.async_request_refresh.assert_not_awaited()
    select.coordinator.async_set_updated_data.assert_called_once()
    # Unrelated system fields must survive the merge.
    assert select.coordinator.data["system"]["firmwareVersion"] == "1.0"


def test_unavailable_when_offline() -> None:
    select = _select(system={"mode": "Powerbaas"}, online=False)

    assert RgbModeSelect.available.fget(select) is False
