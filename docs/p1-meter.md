# P1 Meter

Connects your Powerbaas P1 meter device to Home Assistant, allowing you to monitor your energy meter, solar and dynamic tariff data directly in Home Assistant.

## Features

- **Energy meter data**: power usage, delivered/returned energy (high/low tariff), gas consumption, per-phase voltage and current
- **Solar production**: current output and total production
- **Dynamic tariffs**: usage and return price per kWh
- **Device page**: all sensors are grouped under a single Powerbaas device, with a separate "Diagnostics" section for WiFi strength, firmware version, uptime and last update

## Configuration

1. Go to Settings → Devices & Services → Add Integration
2. Search for "Powerbaas" and choose **P1 Meter** in the device type menu
3. Enter the IP address of your Powerbaas device (e.g. `http://192.168.1.100`) and optionally a name
4. The integration will create a device with all available sensors

If your device's IP address changes later, go to the integration's options to update the host without removing and re-adding it.

## Upgrading from 1.1.0 to 2.0.0

> **Important:** entity names changed in 2.0.0. Every entity now gets your device's name as a prefix (e.g. `sensor.power_delivered_low` becomes `sensor.powerbaas_power_delivered_low`, based on the name you gave the device during setup).

This happens automatically the first time the integration reloads after updating — your existing entities are renamed in place, so their history, statistics and `unique_id` are preserved, no duplicates are created. However, **any automation, script or dashboard card that references the old entity ID directly will need to be updated** to the new, prefixed entity ID.

## Sensors Created

### Main sensors
- `Power Usage` - Current power usage (W)
- `Energy Delivered High` / `Energy Delivered Low` - Energy delivered to the home (kWh)
- `Energy Returned High` / `Energy Returned Low` - Energy returned to the grid (kWh)
- `Gas Consumption` - Gas usage (m³)
- `Voltage L1/L2/L3` - Voltage per phase (V)
- `Current L1/L2/L3` - Current per phase (A)
- `Power Usage L1/L2/L3` - Power usage per phase (W)
- `Solar Current Output` - Current solar power production (W)
- `Solar Total Production` - Total solar energy produced (kWh)
- `Dynamic Tariff - Usage` / `Dynamic Tariff - Return` - Dynamic energy prices (ct/kWh)

### Diagnostic sensors
- `Powerbaas WiFi Strength` - WiFi signal strength (dBm)
- `Powerbaas Firmware Version` - Firmware version
- `Powerbaas Uptime` - Device boot time (timestamp)
- `Powerbaas Last Updated` - Last data fetch timestamp
- `Powerbaas IP Address` - Device's current IP address
