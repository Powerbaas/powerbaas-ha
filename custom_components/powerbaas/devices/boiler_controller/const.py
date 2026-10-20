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

# Battery priority (optional). Lets a home battery charge first; Auto mode
# only gives the boiler what the battery can't absorb. Battery power is
# either one signed sensor or separate charge/discharge sensors (both >= 0,
# e.g. Zendure's outputPackPower/packInputPower).
CONF_BATTERY_SENSOR_TYPE = "battery_sensor_type"
CONF_BATTERY_POWER_SENSOR = "battery_power_sensor"
CONF_BATTERY_CHARGE_NEGATIVE = "battery_charge_negative"
CONF_BATTERY_CHARGE_SENSOR = "battery_charge_sensor"
CONF_BATTERY_DISCHARGE_SENSOR = "battery_discharge_sensor"
CONF_BATTERY_SOC_SENSOR = "battery_soc_sensor"
CONF_BATTERY_FULL_SOC = "battery_full_soc"
CONF_BATTERY_MAX_CHARGE_WATTS = "battery_max_charge_watts"
# Optional near-full taper: from CONF_BATTERY_TAPER_SOC up to full, only
# CONF_BATTERY_TAPER_WATTS (including what the battery already takes) stays
# reserved instead of the whole max charge power, since a battery tops off
# (or calibrates) slowly there. Unset (both None) disables it.
CONF_BATTERY_TAPER_SOC = "battery_taper_soc"
CONF_BATTERY_TAPER_WATTS = "battery_taper_watts"
# Watts Auto mode always leaves unused, battery or not - a buffer against
# brief grid import while the boiler is still ramping down.
CONF_SAFETY_MARGIN_WATTS = "safety_margin_watts"

BATTERY_SENSOR_TYPE_NONE = "none"
BATTERY_SENSOR_TYPE_NET = "net"
BATTERY_SENSOR_TYPE_SPLIT = "split"
BATTERY_SENSOR_TYPES = [BATTERY_SENSOR_TYPE_NONE, BATTERY_SENSOR_TYPE_NET, BATTERY_SENSOR_TYPE_SPLIT]

DEFAULT_BATTERY_FULL_SOC = 99
DEFAULT_BATTERY_MAX_CHARGE_WATTS = 800
DEFAULT_SAFETY_MARGIN_WATTS = 0

# Battery stall detection: while the battery's charge power hasn't moved by
# more than BATTERY_STALL_DELTA_WATTS for BATTERY_STALL_SECONDS despite
# surplus being left for it, it can't take more right now (calibration,
# BMS taper, temperature, a charge limit) and the boiler takes that headroom
# too. A stall is re-checked every BATTERY_STALL_RECHECK_SECONDS by
# reserving the headroom again, since a battery that recovered can't show
# it while the boiler is absorbing the surplus it would ramp up on.
# BATTERY_STALL_SECONDS must outlast the battery's own reaction time to
# export - e.g. Zendure Manager takes 30-70 s to switch from idle or
# discharging to charging.
BATTERY_STALL_SECONDS = 120
BATTERY_STALL_DELTA_WATTS = 50
BATTERY_STALL_RECHECK_SECONDS = 300

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

# Calibration service names (bc_-prefixed since services.yaml is shared
# across all device types under the single "powerbaas" domain)
SERVICE_RUN_CALIBRATION = "bc_run_calibration"
SERVICE_CANCEL_CALIBRATION = "bc_cancel_calibration"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

# Poll interval while waiting for device calibration to complete
CALIBRATION_POLL_SECONDS = 5

# Max heating watts presets
MAX_HEATING_WATTS_OPTIONS = [3500, 3000, 2500, 2000, 1500]
DEFAULT_MAX_HEATING_WATTS = 2000

# Min heating watts floor (HA-side only, applied in Auto mode)
DEFAULT_MIN_HEATING_WATTS = 0

# Flat field-mapped sensors, built by a single generic entity in sensor.py
# Tuple: (name, path, unit, device_class, state_class, multiplier, entity_category, icon, unique_suffix, enabled_default)
#
# path[0] selects the root: "status" -> /api/status, "system" -> /api/system's "system" object.
# unique_suffix is independent from path (unlike p1_meter) so it can preserve
# today's already-live entity IDs even where they don't match the JSON field name.
# enabled_default mirrors HA's own convention (e.g. Shelly) for sensors that
# are useful to some users but noisy/unneeded for most - they're created
# disabled and can be enabled per-install from the entity's settings.
MAIN_SENSORS = [
    ("Device Power", ["status", "power"], "W", "power", "measurement", 1, None, "mdi:flash", "device_power", True),
    ("Heating Percentage", ["status", "heatingPercentage"], "%", None, "measurement", 1, None, "mdi:brightness-percent", "device_heating_percentage", False),
    ("Internal Temperature", ["status", "temperature"], "°C", "temperature", "measurement", 1, None, "mdi:thermometer", "device_temperature", True),
    ("External Temperature", ["status", "temperatureExternal"], "°C", "temperature", "measurement", 1, None, "mdi:thermometer", "device_temperature_external", False),
    ("Device Energy", ["status", "total"], "kWh", "energy", "total_increasing", 1000, None, "mdi:lightning-bolt", "device_energy", False),
]

# Note: the device's own upSince/uptimeSeconds fields change on every poll,
# which would otherwise create a new sensor state (and log/history entry)
# every cycle. "bootTime" is a coordinator-derived field (see
# BoilerControllerCoordinator._apply_boot_time) that stays fixed across polls
# unless the device actually reboots.
DIAGNOSTIC_SENSORS = [
    ("Firmware Version", ["system", "firmwareVersion"], None, None, None, 1, EntityCategory.DIAGNOSTIC, "mdi:chip", "device_firmware_version", True),
    ("WiFi Strength", ["system", "wifiStrength"], "dBm", "signal_strength", "measurement", 1, EntityCategory.DIAGNOSTIC, "mdi:wifi-strength-2", "device_wifi_strength", False),
    ("Up Since", ["system", "bootTime"], None, "timestamp", None, 1, EntityCategory.DIAGNOSTIC, "mdi:calendar-clock", "device_up_since", True),
    ("IP Address", ["system", "ip"], None, None, None, 1, EntityCategory.DIAGNOSTIC, "mdi:ip-network", "device_ip", True),
    # Coordinator-computed (Auto mode only): grid surplus after battery
    # priority and safety margin - what the boiler is allowed to add.
    ("Available Surplus", ["available_surplus"], "W", "power", "measurement", 1, EntityCategory.DIAGNOSTIC, "mdi:flash", "available_surplus", True),
]
