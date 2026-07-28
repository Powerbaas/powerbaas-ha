# CLAUDE.md

Project-specific conventions for working on this repo. See `readme.md` for
what the integration does, and `docs/*.md` for per-device-type behavior.

## Repo layout

- `custom_components/powerbaas/` - the Home Assistant integration (HACS package). Each device type (`devices/boiler_controller/`, `devices/p1_meter/`) has its own client, controller/coordinator, and entity platform files (`sensor.py`, `number.py`, `select.py`, `button.py`).

## Conventions

### Entity icons (mdi)

Pick icons by the physical quantity an entity represents, not just
"electricity-ish":

- **`mdi:flash`** - instantaneous power entities, unit **W** (e.g. a power sensor, a target-watts number).
- **`mdi:lightning-bolt`** - cumulative energy entities, unit **kWh** (e.g. a total-energy sensor).

Don't mix these up - a Watts-unit entity should never get `mdi:lightning-bolt`
and vice versa. This applies across all device types in
`custom_components/powerbaas`, not just Boiler Controller.
