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

   If a Powerbaas P1 Meter is set up in this integration, its **Power Usage** sensor (net, signed) is listed first and preselected as the net power sensor, so it takes priority by default. You can still pick a different sensor.

You can change the power sensor or the module URL later from the integration's options.

## Control modes

Set via the **Control Mode** select entity:

- **Auto** - the controller computes the current grid surplus and adjusts the boiler's heating percentage automatically
- **Manual** - heats at a fixed wattage, set via the **Target Power** number entity. In Auto/On/Off mode, **Target Power** is read-only and mirrors the wattage the controller is currently commanding (in Auto mode this is a live log of the auto-computed value), so it stays available across mode switches instead of only showing up in Manual mode. Its value is flushed to storage right before Home Assistant shuts down, so it survives a restart without writing to disk on every Auto-mode tick.
- **On** - heating element always at 100%
- **Off** - heating element always off

## Calibration

The BC module measures the actual wattage at each heating percentage so the controller can convert requested watts into an accurate dimmer setting. Calibration happens automatically over time, so this is optional - use it only if you want an immediate, complete curve. It's triggered as an action, not an entity, since it's a one-off operation rather than an ongoing device state:

- `powerbaas.bc_run_calibration` - starts a sweep. Make sure the boiler has cooled down first, otherwise the heating element can't reach the higher setpoints and the resulting curve will be incomplete. The sweep takes at least 6 minutes. Home Assistant shows a persistent notification with these instructions when the action runs, and another if it fails.
- `powerbaas.bc_cancel_calibration` - cancels an active sweep after the current step.

Both accept an optional `config_entry_id` field, required only when you have more than one Boiler Controller configured. Call them from Developer Tools → Actions, a script, or an automation.

## Safety limit

Requested power is always clamped to the **Max Heating Power** select, which mirrors the module's own configurable ceiling (matches your meter cupboard's breaker: 3500 / 3000 / 2500 / 2000 / 1500 W). The module also enforces this ceiling itself.

**Minimum Heating Power** sets a floor (in watts) that's applied only in **Auto** mode - useful for boilers that need to stay powered (e.g. for WiFi) even without solar surplus. It has no effect in Manual, On, or Off mode.

## Battery priority

Optional, set in the last step of the config/options flow. If you have a home battery, it charges first: in **Auto** mode the boiler only gets the surplus the battery can't take, and backs off whenever the battery discharges, so the battery never feeds the boiler.

The controller needs:

- **Battery power** - either one sensor (charging positive, discharging negative; a toggle flips this if your battery reports it the other way round) or two separate sensors for charge and discharge power (both always >= 0, e.g. Zendure).
- **Battery charge level** (%) - optional but recommended; from **Battery counts as full from** (default 99%) the boiler gets the full surplus. Below that, the battery keeps priority no matter what its power does - batteries like Zendure pause for up to minutes while switching between charging and discharging, and the boiler must not grab the surplus in the meantime.
- **Battery max charge power** (default 800 W).

How the surplus is split (example: panels 1200 W, battery max 800 W):

- **Battery charging at max (800 W)** - the boiler gets the remaining ±400 W.
- **Battery charging below max (500 W) and still ramping up** - the 300 W it can still take is held back for it; the boiler gets what's left.
- **Battery stuck at 500 W, without a charge level sensor** (calibrating, almost full, temperature-limited, a charge limit) - if its charge power stays put for 2 minutes while surplus is left for it, the boiler takes that 300 W too. A battery that's still switching over from discharging to charging (which can take a minute, e.g. Zendure) isn't treated as stuck. Every 5 minutes the headroom is offered to the battery again, and the stall clears as soon as there's no surplus left (e.g. a cloud).
- **Battery full** - the boiler gets the full surplus.
- **Battery discharging** - the boiler backs off by that amount.

If the battery sensors are unavailable, the controller falls back to plain grid surplus (the battery then temporarily loses priority, grid import isn't affected).

**Safety margin** (W, default 0) is always left unused in Auto mode, with or without a battery - a buffer against brief grid import while the boiler is still ramping down after e.g. a cloud.

The **Available Surplus** diagnostic sensor shows the surplus Auto mode is working with after battery priority and safety margin; the **Status** sensor's `battery_stalled` attribute shows whether the battery's headroom is currently released to the boiler.

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
- `Status` (sensor) - high-level state (Idle / Running / Calibration / Error / Offline) plus diagnostic attributes
- Device sensors read from the module's `/api/status`: power, heating percentage, internal/external temperature (external is unavailable when no probe is mapped to that role), energy
- Diagnostic sensors read from the module's `/api/system`: firmware version, WiFi strength, up-since, IP address
- `Available Surplus` (diagnostic sensor, W) - Auto mode's surplus after battery priority and safety margin; unavailable outside Auto mode
