DOMAIN = "powerbaas"

CONF_DEVICE_TYPE = "device_type"

DEVICE_TYPE_P1_METER = "p1_meter"
DEVICE_TYPE_BOILER_CONTROLLER = "boiler_controller"
DEVICE_TYPES = [DEVICE_TYPE_P1_METER, DEVICE_TYPE_BOILER_CONTROLLER]

# Device types hidden from the "add device" menu and zeroconf discovery while
# still under development. Config entries that already exist for a type in
# here keep working normally - this only blocks *newly adding* that type.
# Remove a type from this set once it's ready for general release.
DISABLED_DEVICE_TYPES = set()
