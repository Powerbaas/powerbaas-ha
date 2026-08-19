"""Light entity command mapping against a fake coordinator/client."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_EFFECT, ATTR_RGB_COLOR

from custom_components.powerbaas.devices.rgb.light import RgbLight


def _light(*, rgb: dict, system: dict | None = None, online: bool = True) -> RgbLight:
    client = SimpleNamespace(async_set_rgb=AsyncMock(return_value=True))
    coordinator = SimpleNamespace(
        data={"rgb": rgb, "system": system or {"mode": "Standalone"}},
        device_online=online,
        device_name="Powerbaas RGB",
        device_url="http://rgb.local",
        client=client,
        async_request_refresh=AsyncMock(),
    )
    entry = MagicMock()
    entry.entry_id = "rgb_entry"
    light = object.__new__(RgbLight)
    light.coordinator = coordinator
    light._entry = entry
    light._attr_unique_id = "rgb_entry_light"
    light._attr_device_info = {}
    return light


async def test_turn_on_sends_on_flag() -> None:
    light = _light(rgb={"ison": False, "brightness": 50})

    await RgbLight.async_turn_on(light)

    light.coordinator.client.async_set_rgb.assert_awaited_once_with(on=1)


async def test_turn_on_with_brightness_and_color() -> None:
    light = _light(rgb={"ison": True, "brightness": 50})

    await RgbLight.async_turn_on(
        light, **{ATTR_BRIGHTNESS: 200, ATTR_RGB_COLOR: (10, 20, 30)}
    )

    light.coordinator.client.async_set_rgb.assert_awaited_once_with(
        on=1, brightness=200, r=10, g=20, b=30, effect="solid"
    )


async def test_turn_on_with_rainbow_effect() -> None:
    light = _light(rgb={"ison": True, "brightness": 50, "isSolid": True})

    await RgbLight.async_turn_on(light, **{ATTR_EFFECT: "rainbow"})

    light.coordinator.client.async_set_rgb.assert_awaited_once_with(on=1, effect="rainbow")


async def test_turn_off_sends_on_zero() -> None:
    light = _light(rgb={"ison": True})

    await RgbLight.async_turn_off(light)

    light.coordinator.client.async_set_rgb.assert_awaited_once_with(on=0)


def test_state_from_status() -> None:
    light = _light(
        rgb={
            "ison": True,
            "brightness": 80,
            "solidR": 1,
            "solidG": 2,
            "solidB": 3,
            "isSolid": True,
            "effect": "solid",
        }
    )

    assert RgbLight.is_on.fget(light) is True
    assert RgbLight.brightness.fget(light) == 80
    assert RgbLight.rgb_color.fget(light) == (1, 2, 3)
    assert RgbLight.effect.fget(light) == "solid"


def test_unavailable_when_offline() -> None:
    light = _light(rgb={"ison": True}, online=False)

    assert RgbLight.available.fget(light) is False
