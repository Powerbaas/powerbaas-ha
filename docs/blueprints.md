# Blueprints

Ready-made Home Assistant automation blueprints for Powerbaas devices live in
[`blueprints/automation/powerbaas/`](../blueprints/automation/powerbaas/) in
this repository.

**These are not installed by HACS or the manual install steps** - those only
copy `custom_components/powerbaas`. Blueprints always have to be imported
separately, the same way for every integration; use one of the two ways
below.

## Installing a blueprint

Either:

- Click one of the **Import Blueprint** badges below (opens Home Assistant
  with the blueprint URL pre-filled), or
- Copy the `.yaml` file into your Home Assistant config's
  `blueprints/automation/powerbaas/` folder and reload blueprints (or
  restart Home Assistant).

Then create a new automation from the imported blueprint under
**Settings → Automations & Scenes → Create Automation → Use Blueprint**, and
fill in the entity/value inputs it asks for.

## General (all device types)

### Device Offline Notification

[![Open your Home Assistant instance and show the blueprint import dialog with the Device Offline Notification blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FPowerbaas%2Fpowerbaas-ha%2Fmain%2Fblueprints%2Fautomation%2Fpowerbaas%2Fdevice_offline_notify.yaml)

Runs your choice of actions when a device's Status sensor reports `Offline`,
and again once it recovers (leaves the `Offline` state). Works for any of
the four device types - P1 Meter, Boiler Controller, Airco Bridge, Powerbaas
RGB - since they all follow the same offline-detection pattern; just pick
the Status sensor of the device you want to watch.

## Boiler Controller blueprints

See [Boiler Controller](boiler-controller.md) for the entities/modes these
reference.

### Scheduled Calibration

[![Open your Home Assistant instance and show the blueprint import dialog with the Scheduled Calibration blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FPowerbaas%2Fpowerbaas-ha%2Fmain%2Fblueprints%2Fautomation%2Fpowerbaas%2Fboiler_calibration_schedule.yaml)

Runs a full calibration sweep (`powerbaas.bc_run_calibration`) on a
configurable day/time each week. Calibration happens automatically over
time as the controller operates, so this is entirely optional - use it only
if you want to force an immediate, complete curve on a schedule (e.g. after
installing a new heating element) instead of calling the action manually.
Make sure the scheduled time is one where the boiler is reliably cooled
down.

### Daily Full Power

[![Open your Home Assistant instance and show the blueprint import dialog with the Daily Full Power blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FPowerbaas%2Fpowerbaas-ha%2Fmain%2Fblueprints%2Fautomation%2Fpowerbaas%2Fboiler_daily_full_power.yaml)

Once a day, sets Control Mode to `On` (100% heating) for a configurable
duration, then switches back to `Auto`. Useful to guarantee a full daily
heat-up (e.g. legionella protection) even on days without enough solar
surplus. Skips the run if calibration is active.

### EMS Setpoint Control

[![Open your Home Assistant instance and show the blueprint import dialog with the EMS Setpoint Control blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FPowerbaas%2Fpowerbaas-ha%2Fmain%2Fblueprints%2Fautomation%2Fpowerbaas%2Fboiler_ems_setpoint.yaml)

Mirrors an external EMS/energy-management setpoint (a `sensor` or
`input_number` holding a watt value) into the Boiler Controller: switches
Control Mode to `Manual` and writes the value to Target Power whenever the
setpoint source changes.

Works with [EMHASS](https://github.com/davidusb-geek/emhass-add-on) out of
the box - point the setpoint source at its deferrable-load output sensor
(e.g. `sensor.p_deferrable0`), which already reports 0 W or the appliance's
nominal wattage per optimized slot.

### EMS Watchdog

[![Open your Home Assistant instance and show the blueprint import dialog with the EMS Watchdog blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FPowerbaas%2Fpowerbaas-ha%2Fmain%2Fblueprints%2Fautomation%2Fpowerbaas%2Fboiler_ems_watchdog.yaml)

Pair this with EMS Setpoint Control. If the setpoint source goes
unavailable, or simply stops updating for longer than a configurable
timeout while Control Mode is `Manual`, switches Control Mode back to
`Auto` so the boiler doesn't get stuck heating at a stale setpoint.
Particularly useful with EMHASS: if the add-on stops running, its output
sensor stays at its last value instead of going unavailable, so the
staleness check here is what actually catches it.

### Dynamic Price Boost

[![Open your Home Assistant instance and show the blueprint import dialog with the Dynamic Price Boost blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FPowerbaas%2Fpowerbaas-ha%2Fmain%2Fblueprints%2Fautomation%2Fpowerbaas%2Fboiler_price_boost.yaml)

Boosts to `On` (100% heating) whenever a dynamic import-price sensor (e.g.
the P1 Meter's "Dynamic Tariff - Usage" sensor, which is disabled by
default) drops below a configurable threshold - free or negative pricing,
for example - and switches back to `Auto` once the price rises above that
threshold again, or after a maximum duration, whichever comes first.

### Manual Mode Timeout

[![Open your Home Assistant instance and show the blueprint import dialog with the Manual Mode Timeout blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FPowerbaas%2Fpowerbaas-ha%2Fmain%2Fblueprints%2Fautomation%2Fpowerbaas%2Fboiler_manual_mode_timeout.yaml)

Switches back to `Auto` if Control Mode is left in `Manual` for longer than
a configurable timeout - e.g. someone switched it manually from the UI and
forgot to switch back. For a `Manual` mode driven by an external EMS
setpoint, use EMS Watchdog instead, which reacts to the setpoint going
stale rather than a fixed timeout.
