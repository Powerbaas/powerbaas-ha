# CLAUDE.md

Project-specific conventions for working on this repo. See `readme.md` for
what the integration does, and `docs/*.md` for per-device-type behavior and
testing.

## Repo layout

- `custom_components/powerbaas/` - the Home Assistant integration (HACS package). Each device type (`devices/boiler_controller/`, `devices/p1_meter/`, `devices/airco_bridge/`, `devices/rgb/`) has its own client, controller/coordinator, and entity platform files (`sensor.py`, `number.py`, `select.py`, `button.py`, `climate.py`, `light.py`, `switch.py`).

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
entry schema changes - e.g. a new `unique_id` format, a bump of
`CONFIG_ENTRY_VERSION` in `const.py` (which drives both `config_flow.py`'s
`VERSION` and the target version in `__init__.py`'s `async_update_entry`
call) plus its matching `async_migrate_entry` step in `__init__.py`, or
anything else that needs a migration path for existing installs. Users
diagnose issues by integration version, so schema changes need to be visible
in the version number even without an accompanying user-facing feature.

### Poll/scan interval configurability

P1 meter's `scan_interval` is a real, user-configurable setting (5-60s,
`SCAN_INTERVAL_SCHEMA` in `p1_meter/config_flow.py`) exposed in both the
initial config flow and the options flow.

Boiler Controller's `poll_interval` is read from config entry data
(`CONF_POLL_INTERVAL` / `DEFAULT_POLL_INTERVAL` in `boiler_controller/const.py`,
`controller.py`) but no config_flow/options_flow step ever sets it - so
despite the code path existing, it's effectively fixed at
`DEFAULT_POLL_INTERVAL` (10s) for every install today. Don't assume it's a
live per-install value.

Airco Bridge's poll interval is the same kind of fixed default
(`DEFAULT_POLL_INTERVAL` 10s in `airco_bridge/const.py`) - there is no
config/options flow field for it.

Powerbaas RGB's poll interval is the same kind of fixed default
(`DEFAULT_POLL_INTERVAL` 10s in `rgb/const.py`) - there is no
config/options flow field for it.

This matters for anything that scales behavior off a device's poll/scan
interval (e.g. request timeouts) - only the P1 meter currently has a real
setting to scale against.

## Testing

See [`docs/testing.md`](docs/testing.md) for how to run tests, test layout
conventions, and the reproduce-first bugfix workflow.

## Commits and PRs

- **Never add a `Co-Authored-By: Claude …` trailer to commit messages.**
  Commits authored by the user should not attribute Claude as a co-author,
  even when Claude assisted. Applies to all commits in this repo and all PRs
  opened from it.
