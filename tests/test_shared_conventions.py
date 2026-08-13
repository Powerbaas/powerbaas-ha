"""Cross-device checks that enforce conventions documented in CLAUDE.md.

Icon conventions (mdi): entities measured in W must use mdi:flash, entities
measured in kWh must use mdi:lightning-bolt - never mixed up. This applies
across all device types, so it's checked here against the raw sensor tables
rather than duplicated per device.
"""

from __future__ import annotations

from custom_components.powerbaas.devices.boiler_controller import const as bc_const
from custom_components.powerbaas.devices.p1_meter import const as p1_const

# Each entry: (label, table, unit_index, icon_index)
_SENSOR_TABLES = [
    ("boiler_controller.MAIN_SENSORS", bc_const.MAIN_SENSORS, 2, 7),
    ("boiler_controller.DIAGNOSTIC_SENSORS", bc_const.DIAGNOSTIC_SENSORS, 2, 7),
    ("p1_meter.MAIN_SENSORS", p1_const.MAIN_SENSORS, 2, 7),
    ("p1_meter.DIAGNOSTIC_SENSORS", p1_const.DIAGNOSTIC_SENSORS, 2, 7),
    ("p1_meter.COMBINED_SENSORS", p1_const.COMBINED_SENSORS, 3, 8),
]


def test_watt_entities_use_flash_icon() -> None:
    for label, table, unit_index, icon_index in _SENSOR_TABLES:
        for entry in table:
            if entry[unit_index] != "W":
                continue
            icon = entry[icon_index]
            assert icon in (None, "mdi:flash"), (
                f"{label}: {entry[0]!r} is a W entity but uses icon {icon!r}, expected mdi:flash"
            )


def test_kwh_entities_use_lightning_bolt_icon() -> None:
    for label, table, unit_index, icon_index in _SENSOR_TABLES:
        for entry in table:
            if entry[unit_index] != "kWh":
                continue
            icon = entry[icon_index]
            assert icon in (None, "mdi:lightning-bolt"), (
                f"{label}: {entry[0]!r} is a kWh entity but uses icon {icon!r}, expected mdi:lightning-bolt"
            )
