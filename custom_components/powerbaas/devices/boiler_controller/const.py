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

# Manual mode defaults
DEFAULT_MANUAL_WATTS = 0

# Seconds between device status polls (updates all sensor values)
DEFAULT_POLL_INTERVAL = 10

# Calibration service names
SERVICE_RUN_CALIBRATION = "run_calibration"
SERVICE_CANCEL_CALIBRATION = "cancel_calibration"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

# Poll interval while waiting for device calibration to complete
CALIBRATION_POLL_SECONDS = 5

# Safety limits
MAX_EXPORT_WATTS = 3500
