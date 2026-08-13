# Testing

## Running tests

```bash
pip install -r requirements.txt -r requirements_test.txt
pytest                                    # whole suite
pytest tests/boiler_controller -v         # one device
pytest tests/p1_meter/test_setup.py -v    # one file
```

Tests live under `tests/<device_type>/`, mirroring
`custom_components/powerbaas/devices/<device_type>/` (e.g.
`tests/boiler_controller/`, `tests/p1_meter/`). Cross-device checks that
enforce a convention documented above (e.g. the icon rule) go in
`tests/test_shared_conventions.py` instead of being duplicated per device.
Most tests build the class under test directly via `object.__new__(...)`
and set only the attributes the method under test reads, rather than
constructing it through a full config entry - see `tests/boiler_controller/
test_controller.py` for the pattern.

## Reproduce-first bugfix workflow

When investigating a reported bug: **write a test that reproduces it first**,
confirm it fails, then write the fix, and confirm the test passes. Leave the
test in place as a regression test - don't fold the fix into an existing
test file's assertions if that loses the "this test exists because of this
bug" link.

Name the file `tests/<device_type>/test_issue_<github-number>_<short-slug>.py`
when there's a GitHub issue number, otherwise a descriptive
`test_<slug>.py` in the same device's test directory.
