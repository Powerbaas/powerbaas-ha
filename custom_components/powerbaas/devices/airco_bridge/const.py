from homeassistant.components.climate import HVACMode
from homeassistant.helpers.entity import EntityCategory

CONF_DEVICE_URL = "device_url"
CONF_DEVICE_ID = "device_id"

# Airco Bridge mDNS hostname prefix (pb-airco-*)
AIRCO_HOST_PREFIX = ("pb-airco-",)

DEFAULT_POLL_INTERVAL = 10
DEFAULT_NAME = "Airco Bridge"

# Firmware /control temperature range (dashboard UI shows 15–26, firmware accepts 15–30)
MIN_TEMPERATURE = 15
MAX_TEMPERATURE = 30
DEFAULT_TEMPERATURE = 21
TEMP_STEP = 1

# DallasTemperature reports this when no probe is connected
TEMP_DISCONNECTED_C = -127.0

# HVAC mode <-> firmware /control?mode=
# Firmware: -1 Off, 0 Auto, 1 Cool, 2 Heat, 3 Dry, 4 Fan
HVAC_MODE_TO_FIRMWARE = {
    HVACMode.OFF: -1,
    HVACMode.AUTO: 0,
    HVACMode.COOL: 1,
    HVACMode.HEAT: 2,
    HVACMode.DRY: 3,
    HVACMode.FAN_ONLY: 4,
}
FIRMWARE_TO_HVAC_MODE = {value: key for key, value in HVAC_MODE_TO_FIRMWARE.items()}

HVAC_MODES = list(HVAC_MODE_TO_FIRMWARE)

# Fan speed <-> firmware /control?fanspeed=
# Firmware: 0 Auto, 1 Min, 2 Low, 3 Medium, 4 High, 5 Max, 6 MediumHigh
FAN_MODE_TO_FIRMWARE = {
    "auto": 0,
    "min": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "max": 5,
    "medium_high": 6,
}
FIRMWARE_TO_FAN_MODE = {value: key for key, value in FAN_MODE_TO_FIRMWARE.items()}

FAN_MODES = list(FAN_MODE_TO_FIRMWARE)

# Tuple: (name, path, unit, device_class, state_class, multiplier, entity_category, icon, unique_suffix)
# path[0] selects the coordinator data root: "temperature" or "system".
MAIN_SENSORS = [
    (
        "Room Temperature",
        ["temperature", "celsius"],
        "°C",
        "temperature",
        "measurement",
        1,
        None,
        "mdi:thermometer",
        "room_temperature",
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
]


def is_valid_temperature(value) -> bool:
    """Return True if value looks like a connected Dallas reading."""
    if not isinstance(value, (int, float)):
        return False
    if value == TEMP_DISCONNECTED_C or value <= -40:
        return False
    return True


def hvac_mode_from_status(airco: dict | None) -> HVACMode:
    """Map firmware airco status to a Home Assistant HVAC mode."""
    if not airco or not airco.get("ison"):
        return HVACMode.OFF
    return FIRMWARE_TO_HVAC_MODE.get(airco.get("mode"), HVACMode.OFF)


def fan_mode_from_status(airco: dict | None) -> str:
    """Map firmware fanspeed to a Home Assistant fan mode string."""
    if not airco:
        return "auto"
    return FIRMWARE_TO_FAN_MODE.get(airco.get("fanspeed"), "auto")


def clamp_temperature(value) -> int:
    """Clamp a setpoint to the firmware-accepted range."""
    try:
        temperature = int(float(value))
    except (TypeError, ValueError):
        temperature = DEFAULT_TEMPERATURE
    return max(MIN_TEMPERATURE, min(MAX_TEMPERATURE, temperature))
