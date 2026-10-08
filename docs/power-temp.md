# PowerTemp

> **Under development** - `power_temp` is listed in `DISABLED_DEVICE_TYPES`
> (`custom_components/powerbaas/const.py`), so it's hidden from the "add
> device" menu and zeroconf discovery. Remove it from that set to release it.

Monitors a PowerTemp from Home Assistant. The PowerTemp is a WiFi meter-cabinet monitor with 16 sensor ports (NTC or DS18B20, auto-detected per port) that warns when a group or connection runs hot.

## How it works

Home Assistant polls the device's `/api/sensors`, `/api/system` and `/api/config` endpoints every 10 seconds. Changes made in Home Assistant are written back with `POST /api/config`; changes made in the device's own web UI show up in Home Assistant on the next poll.

Each connector port with a sensor gets its own **sub-device** under the PowerTemp (e.g. "Groep 3"), so sensors can be put in their own area. The hub device holds the overall status and the shared settings.

## Configuration

1. Go to Settings → Devices & Services → Add Integration
2. Search for "Powerbaas" and choose **PowerTemp** in the device type menu
3. Devices on the local network are auto-discovered (hostnames starting with `pb-pt-`) via zeroconf; you can also enter the URL manually (e.g. `http://pb-pt-xxxxxxxxxxxx.local`)

## Managing sensors

The firmware detects a sensor (NTC or DS18B20) as soon as it's plugged into a port.

- **New sensor** - a repair issue "New sensor found on … port N" appears under Settings → System → Repairs. Fix it to give the sensor a name (and optional calibration offset); this saves it to the device config. Until then it's monitored with the default limits, but if it stops responding the firmware only keeps reporting it as `missing` for 10 minutes before forgetting the port (the repair issue stays open that long too) - an adopted sensor stays `missing` until it's fixed or removed.
- **Rename, calibrate, disable or remove** - the integration's **Configure** button → *Manage sensors*. A disabled sensor is still read but never raises a warning, alarm or `missing` status. Removing a sensor that's still plugged in turns it back into a new sensor.
- **Delete an unplugged sensor** - delete its sub-device from the device page (⋮ → Delete). This also removes it from the device config. Not possible while a sensor is still connected to that port. Plugging a sensor into that port later creates a new sub-device.
- **Ambient reference** - the *Ambient Sensor* select on the hub. Picking a port that isn't configured yet adopts it.

Names set on the device (here or in its web UI) become the sub-device's name; renaming the device in Home Assistant itself only changes it in Home Assistant.

The device URL can be changed under **Configure** → *Device URL*.

## Offline detection

If 5 consecutive `/api/sensors` polls fail, the device is considered offline: all its entities go `unavailable` and a repair issue appears under Settings → System → Repairs. It clears itself once the device responds again.

If the device is unreachable when Home Assistant sets up (or reloads) the integration, setup fails with "Failed setup, will retry" and Home Assistant retries automatically.

## Entities created

Per port sub-device (keyed by port number, so renaming a sensor keeps the same entities):

- `Temperature` (sensor, °C) - with the device's offset applied; unavailable while the port has no valid reading. Attributes: `port`, `sensor_type` (`ntc` / `ds18b20` / `shorted`), `status`, `delta_c`, `age_s`, `ambient`, `enabled`, `configured`
- `Status` (enum sensor) - `ok` / `warning` / `alarm` / `missing` / `error` / `disabled`

New ports get a sub-device automatically, without a reload. A sub-device is named after the sensor's name on the device, or `Temp N` when it has none.

Hub device (`PowerTemp Manager`):

- `Overall Status` (enum sensor) - worst level of all enabled ports: `ok` / `warning` / `fault` / `alarm`
- `Ambient Temperature` (sensor, °C) - from the ambient port; unavailable when none is set
- `Status` (sensor) - Online / Offline
- Config: `Warning Temperature`, `Alarm Temperature`, `Hysteresis`, `Ambient Warning Delta`, `Ambient Alarm Delta` (numbers, °C), `Ambient Delta Limits` (switch), `Ambient Sensor` (select). The firmware validates them together (e.g. alarm must be above warning); a rejected value shows an error and isn't applied
- Diagnostic sensors from `/api/system`: firmware version, WiFi strength, up-since, IP address
