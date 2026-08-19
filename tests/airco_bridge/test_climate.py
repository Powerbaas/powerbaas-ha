"""Climate entity command mapping against a fake coordinator/client."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.climate import HVACMode
from homeassistant.const import ATTR_TEMPERATURE

from custom_components.powerbaas.devices.airco_bridge.climate import AircoBridgeClimate


def _climate(*, airco: dict, temperature: dict | None = None, online: bool = True) -> AircoBridgeClimate:
    client = SimpleNamespace(async_control=AsyncMock(return_value=True))
    coordinator = SimpleNamespace(
        data={"airco": airco, "temperature": temperature or {"celsius": 22.5}, "system": {}},
        device_online=online,
        device_name="Airco Bridge",
        device_url="http://airco.local",
        client=client,
        async_request_refresh=AsyncMock(),
    )
    entry = MagicMock()
    entry.entry_id = "airco_entry"
    climate = object.__new__(AircoBridgeClimate)
    CoordinatorEntity_init_skipped = climate
    CoordinatorEntity_init_skipped.coordinator = coordinator
    climate._entry = entry
    climate._attr_unique_id = "airco_entry_climate"
    climate._last_hvac_mode = HVACMode.HEAT
    climate._attr_supported_features = 0
    climate._attr_device_info = {}
    return climate


async def test_set_hvac_mode_cool_sends_firmware_mode() -> None:
    climate = _climate(airco={"type": 14, "mode": 2, "degrees": 21, "fanspeed": 3, "ison": True})

    await AircoBridgeClimate.async_set_hvac_mode(climate, HVACMode.COOL)

    climate.coordinator.client.async_control.assert_awaited_once_with(
        type_id=14, mode=1, fanspeed=3, temperature=21
    )


async def test_set_hvac_mode_off_sends_mode_minus_one() -> None:
    climate = _climate(airco={"type": 14, "mode": 1, "degrees": 21, "fanspeed": 0, "ison": True})

    await AircoBridgeClimate.async_set_hvac_mode(climate, HVACMode.OFF)

    climate.coordinator.client.async_control.assert_awaited_once_with(
        type_id=14, mode=-1, fanspeed=0, temperature=21
    )


async def test_set_temperature_clamps_and_turns_on_from_off() -> None:
    climate = _climate(airco={"type": 14, "mode": -1, "degrees": 21, "fanspeed": 0, "ison": False})
    climate._last_hvac_mode = HVACMode.HEAT

    await AircoBridgeClimate.async_set_temperature(climate, **{ATTR_TEMPERATURE: 40})

    climate.coordinator.client.async_control.assert_awaited_once_with(
        type_id=14, mode=2, fanspeed=0, temperature=30
    )


async def test_current_temperature_none_when_probe_disconnected() -> None:
    climate = _climate(
        airco={"ison": False},
        temperature={"celsius": -127},
    )

    assert AircoBridgeClimate.current_temperature.fget(climate) is None
