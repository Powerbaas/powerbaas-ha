import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.util import dt as dt_util

from ...const import DOMAIN
from .const import (
    BATTERY_SENSORS,
    MAIN_SENSORS,
    DIAGNOSTIC_SENSORS,
    COMBINED_SENSORS,
    SOLAR_SENSORS,
)

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

    solar_device_info = DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_solar")},
        name="Solar",
        manufacturer="Powerbaas",
        model="Solar",
        via_device=(DOMAIN, entry.entry_id),
    )
    for name, path, unit, device_class, state_class, multiplier, entity_category, icon in SOLAR_SENSORS:
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
                device_info=solar_device_info,
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

    # No update_before_add: the coordinators' async_config_entry_first_refresh()
    # (in __init__.py) has already populated .data by the time entities are
    # built here. update_before_add=True would instead make every
    # CoordinatorEntity's async_update() call coordinator.async_request_refresh()
    # (see CoordinatorEntity.async_update()), firing a redundant extra fetch
    # on every setup/reload for no benefit - matches boiler_controller's
    # sensor.py, which never passes it either.
    async_add_entities(entities)

    battery_coordinator = hass.data[DOMAIN][entry.entry_id]["battery_coordinator"]
    device_registry = dr.async_get(hass)
    # battery_id -> {"entities": [...], "product": str} for whatever the API
    # currently reports - diffed against on every battery_coordinator update
    # so batteries can appear/disappear/rename without a reload.
    known_batteries: dict[int, dict] = {}

    def _battery_device_identifiers(battery_id):
        return {(DOMAIN, f"{entry.entry_id}_battery_{battery_id}")}

    async def _async_handle_battery_update() -> None:
        data = battery_coordinator.data or []
        current_ids = set()
        new_entities = []

        for battery in data:
            battery_id = battery.get("id")
            if battery_id is None:
                continue
            current_ids.add(battery_id)
            product = battery.get("product")

            known = known_batteries.get(battery_id)
            if known is None:
                battery_entities = [
                    PowerBaasBatterySensor(
                        battery_coordinator,
                        entry.entry_id,
                        battery_id,
                        product,
                        name,
                        json_key,
                        unit,
                        device_class,
                        state_class,
                        icon,
                    )
                    for name, json_key, unit, device_class, state_class, icon in BATTERY_SENSORS
                ]
                known_batteries[battery_id] = {"entities": battery_entities, "product": product}
                new_entities.extend(battery_entities)
            elif known["product"] != product:
                device_entry = device_registry.async_get_device(
                    identifiers=_battery_device_identifiers(battery_id)
                )
                if device_entry is not None:
                    device_registry.async_update_device(
                        device_entry.id, name=product, manufacturer=product
                    )
                known["product"] = product

        for battery_id in set(known_batteries) - current_ids:
            removed = known_batteries.pop(battery_id)
            for battery_entity in removed["entities"]:
                await battery_entity.async_remove(force_remove=True)
            device_entry = device_registry.async_get_device(
                identifiers=_battery_device_identifiers(battery_id)
            )
            if device_entry is not None:
                device_registry.async_remove_device(device_entry.id)

        if new_entities:
            async_add_entities(new_entities)

    @callback
    def _handle_battery_update() -> None:
        hass.async_create_task(_async_handle_battery_update())

    await _async_handle_battery_update()
    entry.async_on_unload(battery_coordinator.async_add_listener(_handle_battery_update))


class PowerBaasStatusSensor(CoordinatorEntity, SensorEntity):
    """High-level online/offline status, based on consecutive fetch failures."""

    _attr_should_poll = False
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
    _attr_should_poll = False

    def __init__(self, coordinator, entry_id, device_name, name, path, unit, device_class, state_class, unique_id, multiplier, entity_category=None, icon=None, device_info=None):
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

        if device_info is not None:
            # e.g. the Solar sensors, which belong to their own "Solar"
            # device rather than the main P1 device - see SOLAR_SENSORS'
            # setup in async_setup_entry.
            self._attr_device_info = device_info
            return

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

    _attr_should_poll = False

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


class PowerBaasBatterySensor(CoordinatorEntity, SensorEntity):
    """One field (Power/State of Charge) of one connected battery, as its own HA device."""

    _attr_should_poll = False

    def __init__(
        self,
        coordinator,
        entry_id,
        battery_id,
        product,
        name,
        json_key,
        unit,
        device_class,
        state_class,
        icon,
    ):
        super().__init__(coordinator)
        self._battery_id = battery_id
        self._json_key = json_key
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_icon = icon
        self._attr_unique_id = f"{entry_id}_battery_{battery_id}_{json_key}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_battery_{battery_id}")},
            name=product,
            manufacturer=product,
            model="Battery",
            via_device=(DOMAIN, entry_id),
        )

    @property
    def native_value(self):
        for battery in self.coordinator.data or []:
            if battery.get("id") == self._battery_id:
                return battery.get(self._json_key)
        return None
