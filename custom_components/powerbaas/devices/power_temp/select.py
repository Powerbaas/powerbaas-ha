"""Select entities for the PowerTemp."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...const import DOMAIN
from .const import port_label
from .entity import PowerTempConfigEntity, async_apply

NO_AMBIENT = "None"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([PowerTempAmbientSelect(coordinator, entry)])


class PowerTempAmbientSelect(PowerTempConfigEntity, SelectEntity):
    """Which port is the ambient reference sensor (at most one).

    Picking a port that isn't configured yet adopts it on the device.
    """

    _attr_name = "Ambient Sensor"
    _attr_icon = "mdi:home-thermometer-outline"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, ["sensors"], "ambient_sensor")

    def _labels(self) -> dict[str, int]:
        ports = (self.coordinator.data or {}).get("ports") or {}
        return {port_label(port, item.get("name")): port for port, item in sorted(ports.items())}

    @property
    def options(self) -> list[str]:
        return [NO_AMBIENT, *self._labels()]

    @property
    def current_option(self) -> str | None:
        sensors = self._config_value
        if not isinstance(sensors, list):
            return None
        ambient = next((s.get("port") for s in sensors if s.get("ambient")), None)
        if ambient is None:
            return NO_AMBIENT
        return next(
            (label for label, port in self._labels().items() if port == ambient), NO_AMBIENT
        )

    async def async_select_option(self, option: str) -> None:
        port = None if option == NO_AMBIENT else self._labels()[option]
        await async_apply(self.coordinator, self.coordinator.async_set_ambient_port(port))
