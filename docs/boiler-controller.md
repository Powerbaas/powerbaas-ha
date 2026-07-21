# Boiler Controller

Drives a Powerbaas Boiler Controller (BC) module from Home Assistant, so your boiler soaks up solar surplus instead of it being exported to the grid for (near) nothing.

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
- **Manual** - heats at a fixed wattage, set via the **Manual Power** number entity
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

Requested power is always clamped to a maximum of 3500 W, regardless of control mode.

## Entities created

- `Control Mode` (select) - auto / manual / on / off
- `Manual Power` (number) - target watts used in manual mode
- `Calibrate Start` / `Calibrate Stop` (buttons)
- `Status` (sensor) - high-level state (Idle / Running / Calibration / Error) plus diagnostic attributes
- `Net Power` or `Grid Return` + `Grid Usage` (sensor) - mirrors of your configured power sensor(s)
- `Last Control Update` (sensor) - timestamp of the last heating adjustment
- Device sensors read from the module's `/api/status`: power, heating percentage, temperature, energy, WiFi RSSI, power source
- Diagnostic sensors read from the module's `/api/system`: firmware version, WiFi strength, uptime, up-since, IP address
