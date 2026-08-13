"""Shared fixtures for the powerbaas test suite."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture
def mock_hass() -> MagicMock:
    """A lightweight hass stand-in for harness-style tests that only need
    something "hass-shaped" (e.g. as the `self.hass` on a bare-constructed
    controller) rather than a real event loop / entity registry - use the
    real `hass` fixture (from pytest-homeassistant-custom-component) instead
    when a test actually touches config entries, the entity registry, or
    dispatcher signals end-to-end.
    """
    hass = MagicMock()
    hass.data = {}
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """A minimal config-entry stand-in with real dict-like `.data`/`.options`."""
    entry = MagicMock()
    entry.data = {}
    entry.options = {}
    entry.entry_id = "test_entry_id"
    entry.title = "Test Entry"
    return entry
