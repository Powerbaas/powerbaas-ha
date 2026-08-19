"""Light platform entry point.

Only Powerbaas RGB entries forward this platform, so it delegates
directly - no device-type dispatch needed here.
"""
from .devices.rgb.light import async_setup_entry  # noqa: F401
