from homeassistant.helpers.entity import EntityCategory

DEFAULT_SCAN_INTERVAL = 15
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 60

# HTTP request timeout scales with scan_interval so a slow/hung request can't
# dominate the poll cycle - clamped to stay sane at either end of the range.
TIMEOUT_RATIO = 0.6
MIN_TIMEOUT = 3
MAX_TIMEOUT = 10

# P1 meter mDNS hostname (fixed - unlike the Boiler Controller, every unit
# advertises the same "powerbaas.local" name)
P1_MDNS_HOSTNAME = "powerbaas"

# Main reading sensors - primary energy data
# Tuple: (name, path, unit, device_class, state_class, multiplier, entity_category, icon)
MAIN_SENSORS = [
    ("Power Usage", ["meterReading", "powerUsage"], "W", "power", "measurement", 1, None, None),
    ("Energy Delivered High", ["meterReading", "powerDeliverHigh"], "kWh", "energy", "total_increasing", 1000, None, None),
    ("Energy Delivered Low", ["meterReading", "powerDeliverLow"], "kWh", "energy", "total_increasing", 1000, None, None),
    ("Energy Returned High", ["meterReading", "powerReturnHigh"], "kWh", "energy", "total_increasing", 1000, None, None),
    ("Energy Returned Low", ["meterReading", "powerReturnLow"], "kWh", "energy", "total_increasing", 1000, None, None),
    ("Gas Consumption", ["meterReading", "gas"], "m³", "gas", "total_increasing", 1000, None, None),
    ("Voltage L1", ["meterReading", "voltageL1"], "V", "voltage", "measurement", 1, None, None),
    ("Voltage L2", ["meterReading", "voltageL2"], "V", "voltage", "measurement", 1, None, None),
    ("Voltage L3", ["meterReading", "voltageL3"], "V", "voltage", "measurement", 1, None, None),
    ("Current L1", ["meterReading", "currentL1"], "A", "current", "measurement", 1, None, None),
    ("Current L2", ["meterReading", "currentL2"], "A", "current", "measurement", 1, None, None),
    ("Current L3", ["meterReading", "currentL3"], "A", "current", "measurement", 1, None, None),
    ("Power Usage L1", ["meterReading", "powerUsageL1"], "W", "power", "measurement", 1, None, None),
    ("Power Usage L2", ["meterReading", "powerUsageL2"], "W", "power", "measurement", 1, None, None),
    ("Power Usage L3", ["meterReading", "powerUsageL3"], "W", "power", "measurement", 1, None, None),
    ("Dynamic Tariff - Usage", ["dynamicPrices", "usage"], "ct/kWh", None, None, 1, None, None),
    ("Dynamic Tariff - Return", ["dynamicPrices", "return"], "ct/kWh", None, None, 1, None, None),
]

# Solar sensors - same tuple shape as MAIN_SENSORS (same PowerBaasSensor
# class), but surfaced on their own "Solar" device rather than the main P1
# device - see sensor.py's async_setup_entry, which overrides device_info
# for these specifically. Unique_ids are unchanged from when these lived in
# MAIN_SENSORS, so existing installs just get their Solar entities
# re-parented to the new device on next reload, no migration needed.
SOLAR_SENSORS = [
    ("Solar Current Power", ["solarReading", "current"], "W", "power", "measurement", 1, None, None),
    ("Solar Total Production", ["solarReading", "total"], "kWh", "energy", "total_increasing", 1000, None, None),
]

# Combined High+Low energy totals - summed from two MAIN_SENSORS paths, so
# they need an explicit unique_suffix (no single path to derive one from).
# Tuple: (name, path_a, path_b, unit, device_class, state_class, multiplier, entity_category, icon, unique_suffix)
COMBINED_SENSORS = [
    ("Energy Delivered", ["meterReading", "powerDeliverHigh"], ["meterReading", "powerDeliverLow"],
     "kWh", "energy", "total_increasing", 1000, None, None, "energy_delivered"),
    ("Energy Returned", ["meterReading", "powerReturnHigh"], ["meterReading", "powerReturnLow"],
     "kWh", "energy", "total_increasing", 1000, None, None, "energy_returned"),
]

# Diagnostic sensors - device and system information
DIAGNOSTIC_SENSORS = [
    ("Powerbaas WiFi Strength", ["system", "wifiStrength"], "dBm", "signal_strength", "measurement", 1, EntityCategory.DIAGNOSTIC, "mdi:wifi-strength-2"),
    ("Powerbaas Firmware Version", ["system", "firmwareVersion"], None, None, None, 1, EntityCategory.DIAGNOSTIC, "mdi:chip"),
    ("Powerbaas Uptime", ["system", "upSince"], None, "timestamp", None, 1, EntityCategory.DIAGNOSTIC, "mdi:calendar-clock"),
    ("Powerbaas IP Address", ["system", "ip"], None, None, None, 1, EntityCategory.DIAGNOSTIC, "mdi:ip-network"),
]

# Connected batteries (e.g. Zendure), polled from a separate endpoint and
# surfaced as their own HA devices rather than entities on the P1 meter
# device - see p1_meter/__init__.py's battery_coordinator and sensor.py's
# battery entity/device lifecycle handling.
BATTERY_API_PATH = "/api/battery"

# Fixed - not tied to the main meter's (configurable) scan_interval. Battery
# state changes slowly enough that once a minute is plenty, and decoupling it
# avoids polling batteries as often as e.g. a 5s meter scan_interval would.
BATTERY_SCAN_INTERVAL = 60

# Tuple: (name, json_key, unit, device_class, state_class, icon)
BATTERY_SENSORS = [
    ("Power", "power", "W", "power", "measurement", "mdi:flash"),
    ("State of Charge", "soc", "%", "battery", "measurement", None),
]
