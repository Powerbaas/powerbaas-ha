"""Light entity command mapping against a fake coordinator/client."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

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
    # Mimic DataUpdateCoordinator.async_set_updated_data: it replaces
    # coordinator.data synchronously, in-place, like the real coordinator
    # does - so assertions can read coordinator.data straight after a call.
    coordinator.async_set_updated_data = MagicMock(
        side_effect=lambda data: setattr(coordinator, "data", data)
    )
    entry = MagicMock()
    entry.entry_id = "rgb_entry"
    light = object.__new__(RgbLight)
    light.coordinator = coordinator
    light._entry = entry
    light._attr_unique_id = "rgb_entry_light"
    light._attr_device_info = {}
    light._command_seq = 0
    return light


async def test_turn_on_sends_on_flag() -> None:
    light = _light(rgb={"ison": False, "brightness": 50})

    await RgbLight.async_turn_on(light)

    light.coordinator.client.async_set_rgb.assert_awaited_once_with(on=1)


async def test_turn_on_with_brightness_and_color() -> None:
    # /api/rgb only reliably applies one kind of change per request, so each
    # kind goes out as its own sequential call - see client.py's
    # async_set_rgb docstring. Color is switching the ring into solid mode
    # here (isSolid isn't set on the fixture), so effect=solid follows it.
    light = _light(rgb={"ison": True, "brightness": 50})

    await RgbLight.async_turn_on(
        light, **{ATTR_BRIGHTNESS: 200, ATTR_RGB_COLOR: (10, 20, 30)}
    )

    light.coordinator.client.async_set_rgb.assert_has_awaits(
        [
            call(on=1),
            call(brightness=200),
            call(r=10, g=20, b=30),
            call(effect="solid"),
        ]
    )
    assert light.coordinator.client.async_set_rgb.await_count == 4


async def test_turn_on_color_change_while_already_solid_omits_effect() -> None:
    # Regression test: sending effect=solid alongside r/g/b while the ring
    # is already in solid mode makes the firmware reload its stored solid
    # color instead of applying the new r/g/b - the color change silently
    # reverts after the next poll. Confirmed against a real ring's debug
    # log: three separate color picks, each acknowledged with 200 OK, none
    # of them stuck - the next status poll kept reporting the old color.
    light = _light(
        rgb={"ison": True, "brightness": 166, "isSolid": True, "effect": "solid"}
    )

    await RgbLight.async_turn_on(light, **{ATTR_RGB_COLOR: (255, 137, 14)})

    light.coordinator.client.async_set_rgb.assert_has_awaits(
        [call(on=1), call(r=255, g=137, b=14)]
    )
    assert light.coordinator.client.async_set_rgb.await_count == 2
    assert RgbLight.rgb_color.fget(light) == (255, 137, 14)


async def test_turn_on_switching_to_solid_sends_color_before_effect() -> None:
    # The firmware reads back whatever color was most recently stored when
    # switching effect, so color must be sent (and land) before the
    # effect=solid call that follows it.
    light = _light(rgb={"ison": True, "brightness": 50, "isSolid": False, "effect": "rainbow"})

    await RgbLight.async_turn_on(light, **{ATTR_RGB_COLOR: (10, 20, 30)})

    light.coordinator.client.async_set_rgb.assert_has_awaits(
        [call(on=1), call(r=10, g=20, b=30), call(effect="solid")]
    )


async def test_turn_on_with_rainbow_effect() -> None:
    light = _light(rgb={"ison": True, "brightness": 50, "isSolid": True})

    await RgbLight.async_turn_on(light, **{ATTR_EFFECT: "rainbow"})

    light.coordinator.client.async_set_rgb.assert_has_awaits(
        [call(on=1), call(effect="rainbow")]
    )
    assert light.coordinator.client.async_set_rgb.await_count == 2


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


# Regression tests for the toggle-flicker bug: turning the light on/off used
# to call coordinator.async_request_refresh() right after the command, which
# can race the firmware applying it and read back the stale pre-command
# state - flashing the entity back to the old value until the next poll.
# The fix updates coordinator.data optimistically instead of re-fetching.


async def test_turn_on_reflects_immediately_without_refetch() -> None:
    light = _light(rgb={"ison": False, "brightness": 50})

    await RgbLight.async_turn_on(light)

    assert RgbLight.is_on.fget(light) is True
    light.coordinator.async_request_refresh.assert_not_awaited()
    light.coordinator.async_set_updated_data.assert_called_once()


async def test_turn_off_reflects_immediately_without_refetch() -> None:
    light = _light(rgb={"ison": True, "brightness": 50})

    await RgbLight.async_turn_off(light)

    assert RgbLight.is_on.fget(light) is False
    light.coordinator.async_request_refresh.assert_not_awaited()
    light.coordinator.async_set_updated_data.assert_called_once()


async def test_turn_on_with_brightness_and_color_reflects_immediately() -> None:
    light = _light(rgb={"ison": False, "brightness": 50, "isSolid": False, "effect": "rainbow"})

    await RgbLight.async_turn_on(
        light, **{ATTR_BRIGHTNESS: 200, ATTR_RGB_COLOR: (10, 20, 30)}
    )

    assert RgbLight.is_on.fget(light) is True
    assert RgbLight.brightness.fget(light) == 200
    assert RgbLight.rgb_color.fget(light) == (10, 20, 30)
    assert RgbLight.effect.fget(light) == "solid"


async def test_turn_on_preserves_untouched_fields() -> None:
    light = _light(
        rgb={
            "ison": False,
            "brightness": 77,
            "solidR": 1,
            "solidG": 2,
            "solidB": 3,
        }
    )

    await RgbLight.async_turn_on(light)

    # Only "on" was sent to the firmware - brightness/color must be untouched.
    assert RgbLight.brightness.fget(light) == 77
    assert RgbLight.rgb_color.fget(light) == (1, 2, 3)


# Regression test for the brightness-slider variant of the same flicker bug:
# dragging the slider fires several turn_on calls in quick succession, each
# awaiting its own network round trip. If an older call's response arrives
# after a newer call's (e.g. the device answers slower for that request),
# applying it would clobber the newer, already-applied value.


async def test_out_of_order_response_does_not_clobber_newer_brightness() -> None:
    light = _light(rgb={"ison": True, "brightness": 10})

    release_old_call = asyncio.Event()

    async def async_set_rgb(**params: object) -> bool:
        if params.get("brightness") == 50:
            # The first (older) request is the slow one to answer.
            await release_old_call.wait()
        return True

    light.coordinator.client.async_set_rgb = async_set_rgb

    old_call = asyncio.ensure_future(
        RgbLight.async_turn_on(light, **{ATTR_BRIGHTNESS: 50})
    )
    await asyncio.sleep(0)  # let the old call register and start waiting

    # A newer drag tick fires and completes before the old one answers.
    await RgbLight.async_turn_on(light, **{ATTR_BRIGHTNESS: 100})
    assert RgbLight.brightness.fget(light) == 100

    # The stale response for the old call finally arrives.
    release_old_call.set()
    await old_call

    assert RgbLight.brightness.fget(light) == 100
