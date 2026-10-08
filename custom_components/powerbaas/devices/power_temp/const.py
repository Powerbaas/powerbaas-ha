from homeassistant.helpers.entity import EntityCategory

CONF_DEVICE_URL = "device_url"
CONF_DEVICE_ID = "device_id"

# Powerbaas PowerTemp mDNS hostname prefix (pb-pt-<mac>)
PT_HOST_PREFIX = ("pb-pt-",)

DEFAULT_POLL_INTERVAL = 10
DEFAULT_NAME = "Powerbaas PowerTemp"

# Firmware /api/sensors top-level "status": worst level of all enabled ports.
OVERALL_STATES = ["ok", "warning", "fault", "alarm"]

# Firmware /api/sensors temperatures[].status
PORT_STATES = ["ok", "warning", "alarm", "missing", "error", "disabled"]

# Tuple: (name, path, unit, device_class, state_class, multiplier, entity_category, icon, unique_suffix)
MAIN_SENSORS = [
    (
        "Ambient Temperature",
        ["sensors", "ambientC"],
        "°C",
        "temperature",
        "measurement",
        1,
        None,
        "mdi:home-thermometer",
        "ambient_temperature",
    ),
]

# Note: /api/system is a flat object (no "system" wrapper, unlike RGB/Airco),
# the coordinator stores it under "system" as-is.
DIAGNOSTIC_SENSORS = [
    (
        "Firmware Version",
        ["system", "firmwareVersion"],
        None,
        None,
        None,
        1,
        EntityCategory.DIAGNOSTIC,
        "mdi:chip",
        "device_firmware_version",
    ),
    (
        "WiFi Strength",
        ["system", "wifiStrength"],
        "dBm",
        "signal_strength",
        "measurement",
        1,
        EntityCategory.DIAGNOSTIC,
        "mdi:wifi-strength-2",
        "device_wifi_strength",
    ),
    (
        "Up Since",
        ["system", "upSince"],
        None,
        None,
        None,
        1,
        EntityCategory.DIAGNOSTIC,
        "mdi:calendar-clock",
        "device_up_since",
    ),
    (
        "IP Address",
        ["system", "ip"],
        None,
        None,
        None,
        1,
        EntityCategory.DIAGNOSTIC,
        "mdi:ip-network",
        "device_ip",
    ),
]
