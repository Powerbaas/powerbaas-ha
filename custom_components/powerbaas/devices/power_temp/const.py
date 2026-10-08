from homeassistant.helpers.entity import EntityCategory

from ...const import DOMAIN

CONF_DEVICE_URL = "device_url"
CONF_DEVICE_ID = "device_id"

# PowerTemp mDNS hostname prefix (pb-pt-<mac>)
PT_HOST_PREFIX = ("pb-pt-",)

DEFAULT_POLL_INTERVAL = 10
DEFAULT_NAME = "PowerTemp"
# Hub device name; the config entry title (DEFAULT_NAME or user-given) still
# heads the device group, with the port sub-devices ("Temp N") beside it.
HUB_DEVICE_NAME = "PowerTemp Manager"

# Firmware AppConfig::kMaxSensors / SensorConfig limits
MAX_PORTS = 16
SENSOR_NAME_MAX_BYTES = 31
OFFSET_MIN_C = -10.0
OFFSET_MAX_C = 10.0

# Fixable repair issue per detected-but-unconfigured sensor: <prefix><entry_id>_<port>
NEW_SENSOR_ISSUE_PREFIX = "power_temp_new_sensor_"

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

# Config entities on the hub device, backed by /api/config.
# Tuple: (name, config path, min, max, step, icon, unique_suffix)
CONFIG_NUMBERS = [
    ("Warning Temperature", ["thresholds", "warnC"], 1, 125, 0.5, "mdi:thermometer-alert", "warn_c"),
    ("Alarm Temperature", ["thresholds", "alarmC"], 1, 125, 0.5, "mdi:thermometer-high", "alarm_c"),
    ("Hysteresis", ["thresholds", "hysteresisC"], 0, 10, 0.5, "mdi:arrow-collapse-vertical", "hysteresis_c"),
    ("Ambient Warning Delta", ["delta", "warnC"], 0.5, 100, 0.5, "mdi:delta", "delta_warn_c"),
    ("Ambient Alarm Delta", ["delta", "alarmC"], 0.5, 100, 0.5, "mdi:delta", "delta_alarm_c"),
]


def port_device_identifier(entry_id: str, port: int) -> tuple[str, str]:
    """Device registry identifier of a port's sub-device (the hub uses entry_id)."""
    return (DOMAIN, f"{entry_id}_port_{port}")


def port_from_device(entry_id: str, device_entry) -> int | None:
    """Port number of a sub-device, or None for the hub / another device."""
    prefix = f"{entry_id}_port_"
    for domain, identifier in device_entry.identifiers:
        if domain == DOMAIN and identifier.startswith(prefix):
            suffix = identifier[len(prefix):]
            if suffix.isdigit():
                return int(suffix)
    return None


def port_display_name(port: int, name: str | None) -> str:
    return name or f"Temp {port}"


def port_label(port: int, name: str | None) -> str:
    """Option label that stays unambiguous when two sensors share a name."""
    return f"{name} (port {port})" if name else f"Temp {port}"
