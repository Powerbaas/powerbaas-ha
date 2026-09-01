"""Climate entity command mapping against a fake coordinator/client."""

from __future__ import annotations

import asyncio
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
    # Mimic DataUpdateCoordinator.async_set_updated_data: it replaces
    # coordinator.data synchronously, in-place, like the real coordinator
    # does - so assertions can read coordinator.data straight after a call.
    coordinator.async_set_updated_data = MagicMock(
        side_effect=lambda data: setattr(coordinator, "data", data)
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
    climate._command_seq = 0
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


# Regression tests for the toggle-flicker bug (see tests/rgb/test_rgb_light.py):
# a refresh right after the command can race the firmware applying it and
# read back the stale pre-command state. The fix updates coordinator.data
# optimistically instead of re-fetching.


async def test_set_hvac_mode_reflects_immediately_without_refetch() -> None:
    climate = _climate(airco={"type": 14, "mode": -1, "degrees": 21, "fanspeed": 0, "ison": False})
    climate._last_hvac_mode = HVACMode.HEAT

    await AircoBridgeClimate.async_set_hvac_mode(climate, HVACMode.COOL)

    assert AircoBridgeClimate.hvac_mode.fget(climate) == HVACMode.COOL
    climate.coordinator.async_request_refresh.assert_not_awaited()
    climate.coordinator.async_set_updated_data.assert_called_once()


async def test_set_hvac_mode_off_reflects_immediately_without_refetch() -> None:
    climate = _climate(airco={"type": 14, "mode": 2, "degrees": 21, "fanspeed": 3, "ison": True})

    await AircoBridgeClimate.async_set_hvac_mode(climate, HVACMode.OFF)

    assert AircoBridgeClimate.hvac_mode.fget(climate) == HVACMode.OFF
    climate.coordinator.async_request_refresh.assert_not_awaited()


# Regression test for the temperature-slider variant of the same flicker
# bug: dragging the slider fires several set_temperature calls in quick
# succession, each awaiting its own network round trip. If an older call's
# response arrives after a newer call's, applying it would clobber the
# newer, already-applied value.


async def test_out_of_order_response_does_not_clobber_newer_temperature() -> None:
    climate = _climate(airco={"type": 14, "mode": 2, "degrees": 21, "fanspeed": 3, "ison": True})

    release_old_call = asyncio.Event()

    async def async_control(**params: object) -> bool:
        if params.get("temperature") == 22:
            # The first (older) request is the slow one to answer.
            await release_old_call.wait()
        return True

    climate.coordinator.client.async_control = async_control

    old_call = asyncio.ensure_future(
        AircoBridgeClimate.async_set_temperature(climate, **{ATTR_TEMPERATURE: 22})
    )
    await asyncio.sleep(0)  # let the old call register and start waiting

    # A newer drag tick fires and completes before the old one answers.
    await AircoBridgeClimate.async_set_temperature(climate, **{ATTR_TEMPERATURE: 25})
    assert AircoBridgeClimate.target_temperature.fget(climate) == 25.0

    # The stale response for the old call finally arrives.
    release_old_call.set()
    await old_call

    assert AircoBridgeClimate.target_temperature.fget(climate) == 25.0
