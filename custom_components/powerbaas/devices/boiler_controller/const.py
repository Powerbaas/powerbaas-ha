from homeassistant.helpers.entity import EntityCategory

STEP_POWER_SENSOR = "power_sensor"
STEP_POWER_SENSOR_NET = "power_sensor_net"
STEP_POWER_SENSOR_SPLIT = "power_sensor_split"
STEP_DEVICE_CONFIG = "device_config"

# Configuration keys
# Power sensor selection.
#   - In "net" mode CONF_POWER_SENSOR holds the single signed sensor
#     (negative when exporting, positive when importing).
#   - In "split" mode CONF_RETURN_SENSOR + CONF_USAGE_SENSOR hold the two
#     separate sensors (both always >= 0).
CONF_POWER_SENSOR_TYPE = "power_sensor_type"
CONF_POWER_SENSOR = "power_sensor"
CONF_RETURN_SENSOR = "return_sensor"
CONF_USAGE_SENSOR = "usage_sensor"
CONF_DEVICE_URL = "device_url"
CONF_POLL_INTERVAL = "poll_interval"
CONF_DEVICE_ID = "device_id"

# Power sensor type values
POWER_SENSOR_TYPE_NET = "net"
POWER_SENSOR_TYPE_SPLIT = "split"
POWER_SENSOR_TYPES = [POWER_SENSOR_TYPE_NET, POWER_SENSOR_TYPE_SPLIT]

# Boiler Controller mDNS hostname prefix (pb-bc-*)
BC_HOST_PREFIX = ("pb-bc-",)

# Control modes
BOILER_MODE_AUTO = "auto"
BOILER_MODE_MANUAL = "manual"
BOILER_MODE_ON = "on"
BOILER_MODE_OFF = "off"
BOILER_MODE_CALIBRATING = "calibrating"
BOILER_MODES = [BOILER_MODE_AUTO, BOILER_MODE_MANUAL, BOILER_MODE_ON, BOILER_MODE_OFF]

# Target power default (Manual mode's initial/idle setpoint; Auto mode
# overwrites this at runtime with whatever it last commanded the device to)
DEFAULT_TARGET_WATTS = 0

# Seconds between device status polls (updates all sensor values)
DEFAULT_POLL_INTERVAL = 10

# Minimum drift (seconds) between a freshly computed boot time and the
# previously stored one before it's treated as a real reboot rather than
# request-latency jitter - see BoilerControllerCoordinator._apply_boot_time.
BOOT_TIME_DRIFT_TOLERANCE = 60

# Calibration service names
SERVICE_RUN_CALIBRATION = "run_calibration"
SERVICE_CANCEL_CALIBRATION = "cancel_calibration"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

# Poll interval while waiting for device calibration to complete
CALIBRATION_POLL_SECONDS = 5

# Max heating watts presets
MAX_HEATING_WATTS_OPTIONS = [3500, 3000, 2500, 2000, 1500]
DEFAULT_MAX_HEATING_WATTS = 2000

# Min heating watts floor (HA-side only, applied in Auto mode)
DEFAULT_MIN_HEATING_WATTS = 0

# Flat field-mapped sensors, built by a single generic entity in sensor.py
# Tuple: (name, path, unit, device_class, state_class, multiplier, entity_category, icon, unique_suffix)
#
# path[0] selects the root: "status" -> /api/status, "system" -> /api/system's "system" object.
# unique_suffix is independent from path (unlike p1_meter) so it can preserve
# today's already-live entity IDs even where they don't match the JSON field name.
MAIN_SENSORS = [
    ("Device Power", ["status", "power"], "W", "power", "measurement", 1, None, "mdi:flash", "device_power"),
    ("Heating Percentage", ["status", "heatingPercentage"], "%", None, "measurement", 1, None, "mdi:brightness-percent", "device_heating_percentage"),
    ("Internal Temperature", ["status", "temperature"], "°C", "temperature", "measurement", 1, None, "mdi:thermometer", "device_temperature"),
    ("External Temperature", ["status", "temperatureExternal"], "°C", "temperature", "measurement", 1, None, "mdi:thermometer", "device_temperature_external"),
    ("Device Energy", ["status", "total"], "kWh", "energy", "total_increasing", 1000, None, "mdi:lightning-bolt", "device_energy"),
]

# Note: the device's own upSince/uptimeSeconds fields change on every poll,
# which would otherwise create a new sensor state (and log/history entry)
# every cycle. "bootTime" is a coordinator-derived field (see
# BoilerControllerCoordinator._apply_boot_time) that stays fixed across polls
# unless the device actually reboots.
DIAGNOSTIC_SENSORS = [
    ("Firmware Version", ["system", "firmwareVersion"], None, None, None, 1, EntityCategory.DIAGNOSTIC, "mdi:chip", "device_firmware_version"),
    ("WiFi Strength", ["system", "wifiStrength"], "dBm", "signal_strength", "measurement", 1, EntityCategory.DIAGNOSTIC, "mdi:wifi-strength-2", "device_wifi_strength"),
    ("Up Since", ["system", "bootTime"], None, "timestamp", None, 1, EntityCategory.DIAGNOSTIC, "mdi:calendar-clock", "device_up_since"),
    ("IP Address", ["system", "ip"], None, None, None, 1, EntityCategory.DIAGNOSTIC, "mdi:ip-network", "device_ip"),
]
