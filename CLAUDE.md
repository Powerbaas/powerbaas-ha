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

### Versioning (HACS release)

HACS resolves releases from git tags on this repo, not from any file - but
`custom_components/powerbaas/manifest.json`'s `"version"` field must be kept
in sync with the tag being released (e.g. tag `2.1.0` <-> `"version": "2.1.0"`).
Bump the `manifest.json` version as part of the same change/PR that will be
tagged, don't leave it for release time.

Bump the version (at least a minor bump) whenever the entity/unique_id/config
entry schema changes - e.g. a new `unique_id` format, a config entry
`VERSION` bump in `config_flow.py` plus its matching `async_migrate_entry`
step in `__init__.py`, or anything else that needs a migration path for
existing installs. Users diagnose issues by integration version, so schema
changes need to be visible in the version number even without an accompanying
user-facing feature.
