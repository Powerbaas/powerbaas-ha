from homeassistant.helpers.entity import EntityCategory

CONF_DEVICE_URL = "device_url"
CONF_DEVICE_ID = "device_id"

# Powerbaas RGB mDNS hostname prefix (pb-rgb-*)
RGB_HOST_PREFIX = ("pb-rgb-",)

DEFAULT_POLL_INTERVAL = 10
DEFAULT_NAME = "Powerbaas RGB"

# Firmware /api/mode/update?mode=
APPLICATION_MODES = ["Powerbaas", "HomeWizard", "Standalone"]
MODE_STANDALONE = "Standalone"

# Firmware /api/rgb?effect= (Standalone only)
EFFECT_SOLID = "solid"
EFFECT_RAINBOW = "rainbow"
EFFECTS = [EFFECT_SOLID, EFFECT_RAINBOW]

# Firmware reports -1 when Standalone (no meter selected)
POWER_USAGE_UNAVAILABLE = -1

# Tuple: (name, path, unit, device_class, state_class, multiplier, entity_category, icon, unique_suffix)
MAIN_SENSORS = [
    (
        "Power Usage",
        ["system", "powerUsageWatts"],
        "W",
        "power",
        "measurement",
        1,
        None,
        "mdi:flash",
        "power_usage",
    ),
]

# Note: upSince is a duration string ("Xh MMm SSs"), not an ISO timestamp - keep device_class None.
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
    (
        "Meter URL",
        ["system", "meterUrl"],
        None,
        None,
        None,
        1,
        EntityCategory.DIAGNOSTIC,
        "mdi:link-variant",
        "meter_url",
    ),
]


def is_standalone(system: dict | None) -> bool:
    """Return True when the ring is in Standalone (manual color) mode."""
    return bool(system) and system.get("mode") == MODE_STANDALONE


def is_valid_power_usage(value) -> bool:
    """Return True if value is a real meter reading (not Standalone's -1)."""
    if not isinstance(value, (int, float)):
        return False
    return value != POWER_USAGE_UNAVAILABLE
