# Powerbaas RGB

Controls a Powerbaas RGB from Home Assistant. The ring is a WiFi LED circle that can follow your grid power usage (via a P1 meter or HomeWizard) or be set to a manual color in Standalone mode.

## How it works

Home Assistant polls the ring's `/api/status` and `/api/system` endpoints and exposes a light entity. Changing on/off, brightness, color or effect sends `GET /api/rgb`. Switching application mode sends `GET /api/mode/update`.

Color and effect (`solid` / `rainbow`) are applied by the firmware only in **Standalone** mode. In Powerbaas or HomeWizard mode the ring picks its color from the meter's power reading; on/off and brightness still work.

## Configuration

1. Go to Settings → Devices & Services → Add Integration
2. Search for "Powerbaas" and choose **Powerbaas RGB** in the device type menu
3. Rings on the local network are auto-discovered (hostnames starting with `pb-rgb-`) via zeroconf; you can also enter the URL manually (e.g. `http://pb-rgb-xxxx.local`)
4. After setup, pick **Application Mode** on the device page: Powerbaas (follows a Powerbaas P1 meter), HomeWizard, or Standalone (manual color)

You can change the ring URL later from the integration's options.

## Application Mode

- **Powerbaas** - the ring looks up a Powerbaas P1 meter on the LAN and maps its power usage to a color
- **HomeWizard** - same mapping, using a HomeWizard meter
- **Standalone** - you set color and effect from Home Assistant (or the ring's own web UI)

The **Color Blind** switch changes the power-usage palette used in Powerbaas / HomeWizard mode.

## Offline detection

If 5 consecutive `/api/status` polls fail, the ring is considered offline: the light entity and device sensors go `unavailable` instead of silently continuing to show stale data. A repair issue also appears under Settings → System → Repairs; it clears itself automatically once the ring responds again. Polling keeps retrying in the background the whole time.

If the ring is unreachable when Home Assistant sets up (or reloads) the integration, setup fails with "Failed setup, will retry" on the Integrations page, and Home Assistant retries automatically with backoff until it responds.

## Entities created

- Light entity - on/off, brightness (0–255), RGB color and effect (`solid` / `rainbow`); color and effect apply in Standalone mode
- `Application Mode` (select) - Powerbaas / HomeWizard / Standalone
- `Color Blind` (switch) - alternate palette for meter-follow modes
- `Power Usage` (sensor) - watts reported by the linked meter; unavailable in Standalone
- `Status` (sensor) - Online / Offline
- Diagnostic sensors from `/api/system`: firmware version, WiFi strength, up-since, IP address, meter URL (the linked P1/HomeWizard meter's URL; unavailable in Standalone)
