"""Button platform entry point.

Only Boiler Controller entries forward this platform, so it delegates
directly - no device-type dispatch needed here.
"""
from .devices.boiler_controller.button import async_setup_entry  # noqa: F401
