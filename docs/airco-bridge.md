# Airco Bridge

Controls a Powerbaas Airco Bridge from Home Assistant. The bridge is an IR sender with an optional room-temperature probe: it talks to your air conditioner the same way the original remote does.

## How it works

Home Assistant polls the bridge's `/api/status` and `/api/system` endpoints and exposes a climate entity. Changing HVAC mode, fan speed or setpoint sends `GET /control` to the bridge, which then transmits the matching IR command.

IR is one-way. The climate entity shows the last command the bridge sent, not whether the air conditioner actually received it. The room-temperature sensor is the only live feedback.

## Configuration

1. Go to Settings → Devices & Services → Add Integration
2. Search for "Powerbaas" and choose **Airco Bridge** in the device type menu
3. Bridges on the local network are auto-discovered (hostnames starting with `pb-airco-`) via zeroconf; you can also enter the URL manually (e.g. `http://pb-airco-xxxx.local`)
4. After setup, pick your air conditioner's **Protocol** on the device page so the bridge sends the right IR codes. Leaving it unset makes the firmware try every protocol, which is slow and unreliable.

You can change the bridge URL later from the integration's options.

## Protocol

The **Protocol** select lists every IR protocol the firmware supports (from `/types`). Set this to your air conditioner brand before expecting heat/cool/fan commands to work. The chosen protocol is stored on the bridge itself.

## Offline detection

If 5 consecutive `/api/status` polls fail, the bridge is considered offline: the climate entity and device sensors go `unavailable` instead of silently continuing to show stale data. A repair issue also appears under Settings → System → Repairs; it clears itself automatically once the bridge responds again. Polling keeps retrying in the background the whole time.

If the bridge is unreachable when Home Assistant sets up (or reloads) the integration, setup fails with "Failed setup, will retry" on the Integrations page, and Home Assistant retries automatically with backoff until it responds.

## Entities created

- Climate entity - HVAC mode (off / auto / cool / heat / dry / fan), fan speed, target temperature (15–30 °C), current room temperature when a probe is connected
- `Protocol` (select) - IR protocol used for outgoing commands
- `Room Temperature` (sensor) - Dallas probe in °C; unavailable when no probe is connected
- `Status` (sensor) - Online / Offline
- Diagnostic sensors from `/api/system`: firmware version, WiFi strength, up-since, IP address
