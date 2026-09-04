# P1 Meter

Connects your Powerbaas P1 meter device to Home Assistant, allowing you to monitor your energy meter, solar and dynamic tariff data directly in Home Assistant.

## Features

- **Energy meter data**: power usage, delivered/returned energy (high/low tariff), gas consumption, per-phase voltage and current
- **Solar production**: current output and total production, shown on their own "Solar" device
- **Dynamic tariffs**: usage and return price per kWh
- **Connected batteries**: each battery reported by the meter (e.g. a Zendure) shows up as its own device, with `Power` and `State of Charge` sensors
- **Device page**: all sensors are grouped under a single Powerbaas device, with a separate "Diagnostics" section for WiFi strength, firmware version, uptime and last update

## Configuration

1. Go to Settings → Devices & Services → Add Integration
2. Search for "Powerbaas" and choose **P1 Meter** in the device type menu
3. Enter the IP address of your Powerbaas device (e.g. `http://192.168.1.100`) and optionally a name
4. The integration will create a device with all available sensors

If your device's IP address changes later, go to the integration's options to update the host without removing and re-adding it.

## Offline detection

If 5 consecutive data fetches fail, the device is considered offline: all sensors show as `unavailable` instead of silently keeping their last known value, and a repair issue appears under Settings → System → Repairs. It clears itself automatically once the device responds again. If the device is unreachable when Home Assistant sets up (or reloads) the integration, setup fails with "Failed setup, will retry" on the Integrations page and retries automatically with backoff.

## Upgrading from 1.1.0 to 2.0.0

2.0.0 adds support for multiple devices, so each entity's internal `unique_id` now includes the device's config entry ID instead of being shared across all installs. This migration happens automatically the first time the integration reloads after updating.

Your entity IDs, history, statistics, automations and dashboards are **not** affected — only the internal `unique_id` changes, so no duplicate entities are created and there's nothing you need to update.

## Sensors Created

### Main sensors
- `Power Usage` - Current power usage (W)
- `Energy Delivered High` / `Energy Delivered Low` - Energy delivered to the home (kWh)
- `Energy Returned High` / `Energy Returned Low` - Energy returned to the grid (kWh)
- `Gas Consumption` - Gas usage (m³)
- `Voltage L1/L2/L3` - Voltage per phase (V)
- `Current L1/L2/L3` - Current per phase (A)
- `Power Usage L1/L2/L3` - Power usage per phase (W)
- `Dynamic Tariff - Usage` / `Dynamic Tariff - Return` - Dynamic energy prices (ct/kWh)

### Diagnostic sensors
- `Powerbaas WiFi Strength` - WiFi signal strength (dBm)
- `Powerbaas Firmware Version` - Firmware version
- `Powerbaas Uptime` - Device boot time (timestamp)
- `Powerbaas IP Address` - Device's current IP address

## Solar

Solar production is shown on its own "Solar" device, connected via the P1
meter device:

- `Solar Current Power` - Current solar power production (W)
- `Solar Total Production` - Total solar energy produced (kWh)

## Connected batteries

If the meter's `/api/battery` endpoint reports any connected batteries, each
one gets its own device (named after the battery's `product`, e.g.
"Zendure"), shown as "connected via" the P1 meter device:

- `Power` - Current charge/discharge power (W, negative while discharging)
- `State of Charge` - Battery charge level (%)

A battery's device name updates automatically if the meter starts reporting
a more specific product name later. If a battery is unpaired, its device and
sensors are removed the next time the meter successfully reports the shorter
list; new batteries appear automatically too, no reload needed.

Firmware without this endpoint simply doesn't get any battery devices - it
has no effect on the rest of the P1 meter's sensors or offline detection.
