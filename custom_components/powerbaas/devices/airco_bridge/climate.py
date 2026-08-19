"""Climate entity for the Airco Bridge."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...const import DOMAIN
from .const import (
    DEFAULT_TEMPERATURE,
    FAN_MODE_TO_FIRMWARE,
    FAN_MODES,
    HVAC_MODE_TO_FIRMWARE,
    HVAC_MODES,
    MAX_TEMPERATURE,
    MIN_TEMPERATURE,
    TEMP_STEP,
    clamp_temperature,
    fan_mode_from_status,
    hvac_mode_from_status,
    is_valid_temperature,
)


def _device_info(coordinator, entry: ConfigEntry) -> DeviceInfo:
    system = (coordinator.data or {}).get("system") or {}
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=coordinator.device_name,
        manufacturer="Powerbaas",
        model="Airco Bridge",
        sw_version=str(system.get("firmwareVersion", "Unknown")),
        configuration_url=coordinator.device_url,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([AircoBridgeClimate(coordinator, entry)])


class AircoBridgeClimate(CoordinatorEntity, ClimateEntity):
    """Climate entity backed by the Airco Bridge IR sender + room probe."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = HVAC_MODES
    _attr_fan_modes = FAN_MODES
    _attr_min_temp = MIN_TEMPERATURE
    _attr_max_temp = MAX_TEMPERATURE
    _attr_target_temperature_step = TEMP_STEP
    _attr_icon = "mdi:air-conditioner"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_climate"
        self._last_hvac_mode = HVACMode.HEAT
        features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
        if hasattr(ClimateEntityFeature, "TURN_ON"):
            features |= ClimateEntityFeature.TURN_ON
        if hasattr(ClimateEntityFeature, "TURN_OFF"):
            features |= ClimateEntityFeature.TURN_OFF
        self._attr_supported_features = features
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def available(self) -> bool:
        return self.coordinator.device_online

    @property
    def _airco(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("airco") or {}

    @property
    def hvac_mode(self) -> HVACMode:
        mode = hvac_mode_from_status(self._airco)
        if mode != HVACMode.OFF:
            self._last_hvac_mode = mode
        return mode

    @property
    def target_temperature(self) -> float | None:
        degrees = self._airco.get("degrees")
        if isinstance(degrees, (int, float)) and degrees > 0:
            return float(degrees)
        return float(DEFAULT_TEMPERATURE)

    @property
    def current_temperature(self) -> float | None:
        celsius = ((self.coordinator.data or {}).get("temperature") or {}).get("celsius")
        if is_valid_temperature(celsius):
            return float(celsius)
        return None

    @property
    def fan_mode(self) -> str | None:
        return fan_mode_from_status(self._airco)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._async_send(mode=HVAC_MODE_TO_FIRMWARE[HVACMode.OFF])
            return
        self._last_hvac_mode = hvac_mode
        await self._async_send(mode=HVAC_MODE_TO_FIRMWARE[hvac_mode])

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        mode = self.hvac_mode
        if mode == HVACMode.OFF:
            mode = self._last_hvac_mode
        await self._async_send(
            mode=HVAC_MODE_TO_FIRMWARE[mode],
            temperature=clamp_temperature(temperature),
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode not in FAN_MODE_TO_FIRMWARE:
            raise HomeAssistantError(f"Unsupported fan mode: {fan_mode}")
        mode = self.hvac_mode
        if mode == HVACMode.OFF:
            mode = self._last_hvac_mode
        await self._async_send(
            mode=HVAC_MODE_TO_FIRMWARE[mode],
            fanspeed=FAN_MODE_TO_FIRMWARE[fan_mode],
        )

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(self._last_hvac_mode)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def _async_send(
        self,
        *,
        mode: int,
        fanspeed: int | None = None,
        temperature: int | None = None,
        type_id: int | None = None,
    ) -> None:
        airco = self._airco
        if type_id is None:
            type_id = airco.get("type", -1)
        if fanspeed is None:
            fanspeed = airco.get("fanspeed", 0)
        if temperature is None:
            temperature = clamp_temperature(airco.get("degrees") or DEFAULT_TEMPERATURE)

        ok = await self.coordinator.client.async_control(
            type_id=int(type_id),
            mode=int(mode),
            fanspeed=int(fanspeed),
            temperature=int(temperature),
        )
        if not ok:
            raise HomeAssistantError("Failed to send command to the Airco Bridge")
        await self.coordinator.async_request_refresh()
