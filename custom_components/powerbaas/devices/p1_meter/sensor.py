import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.util import dt as dt_util

from ...const import DOMAIN
from .const import MAIN_SENSORS, DIAGNOSTIC_SENSORS, COMBINED_SENSORS

_LOGGER = logging.getLogger(__name__)


def _parse_timestamp(value):
    """Parse a timestamp string (ISO or 'YYYY-MM-DD HH:MM:SS') into a local datetime."""
    if not value:
        return None
    try:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        if dt.tzinfo is None:
            dt = dt_util.as_local(dt)
        return dt
    except ValueError as err:
        _LOGGER.warning("Error parsing timestamp %s: %s", value, err)
        return None


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_name = hass.data[DOMAIN][entry.entry_id]["name"]

    entities = [PowerBaasStatusSensor(coordinator, entry.entry_id, device_name)]
    for name, path, unit, device_class, state_class, multiplier, entity_category, icon in MAIN_SENSORS + DIAGNOSTIC_SENSORS:
        unique_id = f"{entry.entry_id}_{'_'.join(path).lower()}"
        entities.append(
            PowerBaasSensor(
                coordinator,
                entry.entry_id,
                device_name,
                name,
                path,
                unit,
                device_class,
                state_class,
                unique_id,
                multiplier,
                entity_category,
                icon,
            )
        )

    for name, path_a, path_b, unit, device_class, state_class, multiplier, entity_category, icon, unique_suffix in COMBINED_SENSORS:
        entities.append(
            PowerBaasCombinedEnergySensor(
                coordinator,
                entry.entry_id,
                device_name,
                name,
                path_a,
                path_b,
                unit,
                device_class,
                state_class,
                f"{entry.entry_id}_{unique_suffix}",
                multiplier,
                entity_category,
                icon,
            )
        )

    async_add_entities(entities, True)


class PowerBaasStatusSensor(CoordinatorEntity, SensorEntity):
    """High-level online/offline status, based on consecutive fetch failures."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry_id, device_name):
        super().__init__(coordinator)
        self._attr_name = "Status"
        self._attr_unique_id = f"{entry_id}_status"
        self._attr_icon = "mdi:list-status"

        system_data = coordinator.data.get("system", {}) if coordinator.data else {}

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=device_name,
            manufacturer="Powerbaas",
            model="P1 Meter",
            sw_version=str(system_data.get("firmwareVersion", "Unknown")),
            configuration_url=None,
        )

    @property
    def available(self) -> bool:
        # Always available - "Offline" is a state, not the absence of one.
        return True

    @property
    def native_value(self):
        return "Online" if self.coordinator.device_online else "Offline"


class PowerBaasSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry_id, device_name, name, path, unit, device_class, state_class, unique_id, multiplier, entity_category=None, icon=None):
        super().__init__(coordinator)
        self._attr_name = name
        self._path = path
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_unique_id = unique_id
        self._attr_entity_category = entity_category
        self._attr_icon = icon
        self._multiplier = multiplier
        self._last_value = None

        system_data = coordinator.data.get("system", {}) if coordinator.data else {}

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=device_name,
            manufacturer="Powerbaas",
            model="P1 Meter",
            sw_version=str(system_data.get("firmwareVersion", "Unknown")),
            # Explicit None (not omitted) - entity_platform only clears a
            # previously-stored device registry field when the key is
            # present with value None; leaving it out entirely means "don't
            # touch", so the stale Visit link would otherwise never go away.
            configuration_url=None,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.device_online

    @property
    def native_value(self):
        data = self.coordinator.data
        try:
            if self._attr_device_class == "timestamp":
                for key in self._path:
                    data = data.get(key, {}) if isinstance(data, dict) else None
                return _parse_timestamp(data) if isinstance(data, str) else None

            for key in self._path:
                data = data.get(key, {})

            if isinstance(data, (int, float)):
                value = data / self._multiplier if self._multiplier else data

                if (
                    self._attr_state_class == "total_increasing"
                    and value == 0
                    and self._last_value not in (None, 0)
                ):
                    return self._last_value

                self._last_value = value
                return value

            return data

        except Exception as err:
            _LOGGER.warning("Error accessing sensor path %s: %s", self._path, err)
            return None


class PowerBaasCombinedEnergySensor(CoordinatorEntity, SensorEntity):
    """Sum of two MAIN_SENSORS energy paths, e.g. High + Low tariff totals."""

    def __init__(self, coordinator, entry_id, device_name, name, path_a, path_b, unit, device_class, state_class, unique_id, multiplier, entity_category=None, icon=None):
        super().__init__(coordinator)
        self._attr_name = name
        self._path_a = path_a
        self._path_b = path_b
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_unique_id = unique_id
        self._attr_entity_category = entity_category
        self._attr_icon = icon
        self._multiplier = multiplier
        self._last_value = None

        system_data = coordinator.data.get("system", {}) if coordinator.data else {}

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=device_name,
            manufacturer="Powerbaas",
            model="P1 Meter",
            sw_version=str(system_data.get("firmwareVersion", "Unknown")),
            configuration_url=None,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.device_online

    @staticmethod
    def _read(data, path):
        for key in path:
            data = data.get(key, {}) if isinstance(data, dict) else None
        return data

    @property
    def native_value(self):
        data = self.coordinator.data
        try:
            value_a = self._read(data, self._path_a)
            value_b = self._read(data, self._path_b)
            if not isinstance(value_a, (int, float)) or not isinstance(value_b, (int, float)):
                return None

            total = value_a + value_b
            value = total / self._multiplier if self._multiplier else total

            if (
                self._attr_state_class == "total_increasing"
                and value == 0
                and self._last_value not in (None, 0)
            ):
                return self._last_value

            self._last_value = value
            return value

        except Exception as err:
            _LOGGER.warning(
                "Error accessing combined sensor paths %s + %s: %s",
                self._path_a,
                self._path_b,
                err,
            )
            return None
