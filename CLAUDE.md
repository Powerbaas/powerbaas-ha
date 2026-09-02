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
`coordinator.py`) but no config_flow/options_flow step ever sets it - so
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

### Device offline / unreachable handling (required for every device type)

Every device type must handle the device being unreachable, both at setup
time and during ongoing polling - this is not optional and should be built
in from the first version of a new device type, not added later. P1 meter,
Boiler Controller, Airco Bridge, and RGB all follow the same pattern:

- **Setup gate**: before creating the coordinator, call the client's
  `async_test_connection()` (or equivalent) and raise `ConfigEntryNotReady`
  if it fails, so an offline device shows up as "Failed setup, will retry"
  on the Integrations page instead of silently succeeding.
- **Consecutive-failure counter**: track consecutive failed polls against
  the shared `OFFLINE_AFTER_CONSECUTIVE_FAILURES` constant in `const.py`.
  On hitting the threshold, flip a `device_online` flag to `False`, log a
  warning, and raise an `issue_registry` repair issue (a
  `<device_type>_offline` translation key, with matching entries added to
  both `translations/en.json` and `translations/nl.json`). On the next
  successful poll, flip `device_online` back to `True` and delete the
  issue.
- **Entity availability**: every entity's `available` property (besides a
  dedicated status sensor, see below) should be gated on
  `coordinator.device_online`, so the whole device goes unavailable
  together rather than one missed poll flipping every sensor individually.
- **Status sensor**: include one sensor that is always available and
  reports "Online"/"Offline" as its state, so the device's connectivity is
  visible even while every other entity is unavailable.

All four device types are now built on Home Assistant's
`DataUpdateCoordinator` (P1 meter, RGB, Airco Bridge, and Boiler Controller -
the latter migrated from a hand-rolled `asyncio` poll loop plus
`async_dispatcher_send` signals; see `boiler_controller/coordinator.py`).
Be aware that `DataUpdateCoordinator._async_refresh()` only calls
`async_update_listeners()` for the *first* failed refresh after a success -
every consecutive failure after that is silently skipped (see
`homeassistant/helpers/update_coordinator.py`, the
`last_update_success`/`previous_update_success` check). Since the
`device_online` flag only flips on the Nth failure (at
`OFFLINE_AFTER_CONSECUTIVE_FAILURES`), which is after that first
notification already happened, entities never learn about it and stay
stuck showing "available" unless the code where `device_online` flips
explicitly calls `self.async_update_listeners()` (and again on recovery).
This bit RGB and Airco Bridge in practice, and Boiler Controller's migration
carried the same fix forward - see `_register_failure`/`_register_success`
in `devices/{airco_bridge,rgb,boiler_controller}/{__init__,coordinator}.py`,
and the regression test in
`tests/airco_bridge/test_airco_setup.py::test_listeners_notified_when_device_goes_offline`.

Boiler Controller's coordinator also owns command methods (mode/watts/SSR/
calibration setters) beyond just polling - unlike RGB/Airco's thin
coordinators, this is deliberate: that logic is genuinely device-specific
business logic, not boilerplate, so it doesn't belong split onto entities.
Command-driven fields (`control_mode`, `target_watts`, `max_heating_watts`,
`min_heating_watts`, `calibration_active`) live in `coordinator.data`
alongside the polled `status`/`system` fields, pushed via
`async_set_updated_data()`; `_async_update_data()` carries those
command-driven keys forward from the previous cycle on every poll, since
they aren't re-fetched from the device.

None of the existing device types special-case a specific "not found"
signal (e.g. HTTP 404) differently from other failures (timeout, connection
error, non-200 status) - any failed request counts the same toward the
consecutive-failure counter. Keep new device types consistent with that
unless there's a concrete reason to distinguish "not found" from "device
down".

## Testing

See [`docs/testing.md`](docs/testing.md) for how to run tests, test layout
conventions, and the reproduce-first bugfix workflow.

## Commits and PRs

- **Never add a `Co-Authored-By: Claude …` trailer to commit messages.**
  Commits authored by the user should not attribute Claude as a co-author,
  even when Claude assisted. Applies to all commits in this repo and all PRs
  opened from it.
