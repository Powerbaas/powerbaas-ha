# P1 Meter

Connects your Powerbaas P1 meter device to Home Assistant, allowing you to monitor your energy meter, solar and dynamic tariff data directly in Home Assistant.

## Features

- **Energy meter data**: power usage, delivered/returned energy (high/low tariff), gas consumption, per-phase voltage and current
- **Solar production**: current output and total production, shown on their own "Solar" device
- **Solar from Home Assistant**: already have your solar panels in Home Assistant? Home Assistant can serve them to the P1's custom solar integration (see [below](#solar-from-home-assistant-to-the-p1))
- **Dynamic tariffs**: usage and return price per kWh
- **Connected batteries**: each battery reported by the meter (e.g. a Zendure) shows up as its own device, with `Power` and `State of Charge` sensors
- **Device page**: all sensors are grouped under a single Powerbaas device, with a separate "Diagnostics" section for WiFi strength, firmware version, uptime and last update

## Configuration

1. Go to Settings → Devices & Services → Add Integration
2. Search for "Powerbaas" and choose **P1 Meter** in the device type menu
3. Enter the IP address of your Powerbaas device (e.g. `http://192.168.1.100`) and optionally a name
4. The integration will create a device with all available sensors

If your device's IP address changes later, go to the integration's options to update the host without removing and re-adding it.

Most sensors below are created but **disabled by default** to keep
recorder/history load down, especially at short update intervals - only
`Power Usage`, `Gas Consumption`, `Energy Delivered`, `Energy Returned`,
`Status`, `Powerbaas Uptime` and `Powerbaas IP Address` are enabled out of
the box. Enable any of the others from the entity's page (gear icon →
enable) if you need them.

## Offline detection

If 5 consecutive data fetches fail, the device is considered offline: all sensors show as `unavailable` instead of silently keeping their last known value, and a repair issue appears under Settings → System → Repairs. It clears itself automatically once the device responds again. If the device is unreachable when Home Assistant sets up (or reloads) the integration, setup fails with "Failed setup, will retry" on the Integrations page and retries automatically with backoff.

## Upgrading from 1.1.0 to 2.0.0

2.0.0 adds support for multiple devices, so each entity's internal `unique_id` now includes the device's config entry ID instead of being shared across all installs. This migration happens automatically the first time the integration reloads after updating.

Your entity IDs, history, statistics, automations and dashboards are **not** affected — only the internal `unique_id` changes, so no duplicate entities are created and there's nothing you need to update.

## Sensors Created

### Main sensors
- `Power Usage` - Current power usage (W)
- `Energy Delivered` - Total energy delivered to the home, high + low tariff combined (kWh)
- `Energy Returned` - Total energy returned to the grid, high + low tariff combined (kWh)
- `Gas Consumption` - Gas usage (m³)
- `Energy Delivered High` / `Energy Delivered Low` - Energy delivered to the home, split by tariff (kWh) *(disabled by default)*
- `Energy Returned High` / `Energy Returned Low` - Energy returned to the grid, split by tariff (kWh) *(disabled by default)*
- `Voltage L1/L2/L3` - Voltage per phase (V) *(disabled by default)*
- `Current L1/L2/L3` - Current per phase (A) *(disabled by default)*
- `Power Usage L1/L2/L3` - Power usage per phase (W) *(disabled by default)*
- `Dynamic Tariff - Usage` / `Dynamic Tariff - Return` - Dynamic energy prices (ct/kWh) *(disabled by default)*

### Diagnostic sensors
- `Powerbaas WiFi Strength` - WiFi signal strength (dBm) *(disabled by default)*
- `Powerbaas Firmware Version` - Firmware version *(disabled by default)*
- `Powerbaas Uptime` - Device boot time (timestamp)
- `Powerbaas IP Address` - Device's current IP address

## Solar

Solar production is shown on its own "Solar" device, connected via the P1
meter device. Both sensors are disabled by default:

- `Solar Current Power` - Current solar power production (W)
- `Solar Total Production` - Total solar energy produced (kWh)

### Solar from Home Assistant to the P1

Already have your solar panels in Home Assistant (e.g. through your
inverter's integration)? The P1's firmware has a *custom solar* integration
that polls an HTTP URL for `{"current": <W>, "total": <Wh>}`. Home Assistant
can serve that URL for you:

1. Turn on **Send solar from Home Assistant to the P1**, when adding the P1
   or later under its **Configure** options.
2. Pick a power sensor (current production) and an energy sensor (total
   production). Both are required. kW, kWh and MWh are converted to W and Wh.
   The P1's own Solar sensors are left out of the list, since the P1 would
   then read its own value back.
3. Enter the URL shown in the last step (`http://<home-assistant>:8123/api/webhook/<token>`)
   in the custom solar integration of the P1. You can find it again later in
   the `Solar URL` diagnostic sensor on the Solar device.

How the URL behaves:

- No login is needed: the random token in the URL is what grants access,
  so treat the URL like a password. It stays the same when you run the
  options again, or turn the feature off and back on.
- It only answers requests from your local network (not through Nabu Casa
  or the internet), and only `GET`.
- While one of the two sensors has no value (`unavailable`/`unknown`), it
  answers HTTP 503 instead of a made-up 0.
- Home Assistant must be reachable over plain `http://` from the P1. If you
  only expose Home Assistant over HTTPS, the P1 can't use this URL.

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
