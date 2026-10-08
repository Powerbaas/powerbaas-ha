# Powerbaas PowerTemp

> **Under development** - `power_temp` is listed in `DISABLED_DEVICE_TYPES`
> (`custom_components/powerbaas/const.py`), so it's hidden from the "add
> device" menu and zeroconf discovery. Remove it from that set to release it.

Monitors a Powerbaas PowerTemp from Home Assistant. The PowerTemp is a WiFi meter-cabinet monitor with 16 sensor ports (NTC or DS18B20, auto-detected per port) that warns when a group or connection runs hot.

## How it works

Home Assistant polls the device's `/api/sensors` and `/api/system` endpoints every 10 seconds. Thresholds (warn/alarm, delta vs. ambient), sensor names, offsets and which port is the ambient sensor are configured on the device's own web UI - Home Assistant only reads the resulting temperatures and levels.

## Configuration

1. Go to Settings → Devices & Services → Add Integration
2. Search for "Powerbaas" and choose **Powerbaas PowerTemp** in the device type menu
3. Devices on the local network are auto-discovered (hostnames starting with `pb-pt-`) via zeroconf; you can also enter the URL manually (e.g. `http://pb-pt-xxxxxxxxxxxx.local`)

You can change the device URL later from the integration's options.

## Offline detection

If 5 consecutive `/api/sensors` polls fail, the device is considered offline: all its entities go `unavailable` and a repair issue appears under Settings → System → Repairs. It clears itself once the device responds again.

If the device is unreachable when Home Assistant sets up (or reloads) the integration, setup fails with "Failed setup, will retry" and Home Assistant retries automatically.

## Entities created

Per port that reports a sensor (configured on the device, or newly detected); new ports get entities automatically without a reload. Entities are keyed by port number, so renaming a sensor on the device keeps the same entity:

- `<name>` (sensor, °C) - temperature with the device's offset applied; unavailable while the port has no valid reading. Attributes: `port`, `sensor_type` (`ntc` / `ds18b20` / `shorted`), `status`, `delta_c`, `age_s`, `ambient`, `enabled`
- `<name> Status` (enum sensor) - `ok` / `warning` / `alarm` / `missing` / `error` / `disabled`

`<name>` is the name set on the device, or `Port N` when it has none.

Device-wide:

- `Overall Status` (enum sensor) - worst level of all enabled ports: `ok` / `warning` / `fault` / `alarm`
- `Ambient Temperature` (sensor, °C) - from the port marked as ambient; unavailable when none is set
- `Status` (sensor) - Online / Offline
- Diagnostic sensors from `/api/system`: firmware version, WiFi strength, up-since, IP address
