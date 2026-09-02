# Boiler Controller

Drives a Powerbaas Boiler Controller (BC) module from Home Assistant so surplus solar power heats your boiler instead of being exported to the grid for (near) nothing.

## How it works

The controller watches a power sensor you already have in Home Assistant (your P1 meter's net power sensor, for example) and continuously tells the BC module how hard to heat, so that any surplus solar power is diverted into the boiler.

## Configuration

1. Go to Settings → Devices & Services → Add Integration
2. Search for "Powerbaas" and choose **Boiler Controller** in the device type menu
3. BC modules on the local network are auto-discovered (hostnames starting with `pb-bc-`) via zeroconf; you can also enter the module's URL manually (e.g. `http://pb-bc-xxxx.local`)
4. Pick how grid power is reported in Home Assistant:
   - **Net power sensor** - a single signed sensor that goes negative when exporting to the grid
   - **Split sensors** - two separate sensors, one for grid return (export) and one for grid usage (import), both always ≥ 0

You can change the power sensor or the module URL later from the integration's options.

## Control modes

Set via the **Control Mode** select entity:

- **Auto** - the controller computes the current grid surplus and adjusts the boiler's heating percentage automatically
- **Manual** - heats at a fixed wattage, set via the **Target Power** number entity. In Auto/On/Off mode, **Target Power** is read-only and mirrors the wattage the controller is currently commanding (in Auto mode this is a live log of the auto-computed value), so it stays available across mode switches instead of only showing up in Manual mode. Its value is flushed to storage right before Home Assistant shuts down, so it survives a restart without writing to disk on every Auto-mode tick.
- **On** - heating element always at 100%
- **Off** - heating element always off

## Calibration

The BC module measures the actual wattage at each heating percentage so the controller can convert requested watts into an accurate dimmer setting. Calibration happens automatically over time, but you can trigger a full sweep manually:

- **Calibrate Start** button - starts a sweep. Make sure the boiler has cooled down first, otherwise the heating element can't reach the higher setpoints and the resulting curve will be incomplete. The sweep takes at least 6 minutes.
- **Calibrate Stop** button - cancels an active sweep after the current step.

The same actions are available as services for use in automations/scripts:

- `powerbaas.run_calibration`
- `powerbaas.cancel_calibration`

Both accept an optional `config_entry_id` field, required only when you have more than one Boiler Controller configured.

## Safety limit

Requested power is always clamped to the **Max Heating Power** select, which mirrors the module's own configurable ceiling (matches your meter cupboard's breaker: 3600 / 3000 / 2500 / 2000 W). The module also enforces this ceiling itself.

**Minimum Heating Power** sets a floor (in watts) that's applied only in **Auto** mode - useful for boilers that need to stay powered (e.g. for WiFi) even without solar surplus. It has no effect in Manual, On, or Off mode.

## SSR

The module's SSR relay is independent from the heating percentage output. Toggle it with the **SSR** switch; it reflects the module's live relay state.

## Offline detection

If 5 consecutive `/api/status` polls fail, the module is considered offline: the **Status** sensor shows `Offline`, the **SSR** switch and the device/system sensors (power, temperature, energy, WiFi strength, etc.) go `unavailable`, instead of silently continuing to show stale data. A repair issue also appears under Settings → System → Repairs so it's easy to notice; it clears itself automatically once the module responds again. Polling keeps retrying in the background the whole time.

If the module is unreachable when Home Assistant sets up (or reloads) the integration, setup fails with "Failed setup, will retry" on the Integrations page, and Home Assistant retries automatically with backoff until it responds.

## Entities created

- `Control Mode` (select) - auto / manual / on / off
- `Target Power` (number) - target watts used in manual mode
- `Max Heating Power` (select) - configurable safety ceiling, in watts (breaker presets)
- `Minimum Heating Power` (number) - Auto-mode-only floor, in watts
- `SSR` (switch) - the module's SSR relay state
- `Calibrate Start` / `Calibrate Stop` (buttons)
- `Status` (sensor) - high-level state (Idle / Running / Calibration / Error / Offline) plus diagnostic attributes
- Device sensors read from the module's `/api/status`: power, heating percentage, internal/external temperature (external is unavailable when no probe is mapped to that role), energy
- Diagnostic sensors read from the module's `/api/system`: firmware version, WiFi strength, up-since, IP address
