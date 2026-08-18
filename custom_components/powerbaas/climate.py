"""Climate platform entry point.

Only Airco Bridge entries forward this platform, so it delegates
directly - no device-type dispatch needed here.
"""
from .devices.airco_bridge.climate import async_setup_entry  # noqa: F401
