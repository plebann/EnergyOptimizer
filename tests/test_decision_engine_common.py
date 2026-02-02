"""Tests for decision engine common helpers."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.energy_optimizer.decision_engine.common import resolve_entry
from custom_components.energy_optimizer.const import DOMAIN

pytestmark = pytest.mark.enable_socket


def _mock_entry(entry_id: str, domain: str = DOMAIN) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.domain = domain
    entry.data = {}
    return entry


def test_resolve_entry_with_id_valid() -> None:
    hass = MagicMock()
    entry = _mock_entry("abc")
    hass.config_entries.async_get_entry.return_value = entry

    result = resolve_entry(hass, "abc")

    assert result is entry


def test_resolve_entry_with_id_invalid_domain() -> None:
    hass = MagicMock()
    entry = _mock_entry("abc", domain="other")
    hass.config_entries.async_get_entry.return_value = entry

    result = resolve_entry(hass, "abc")

    assert result is None


def test_resolve_entry_single_entry() -> None:
    hass = MagicMock()
    entry = _mock_entry("abc")
    hass.config_entries.async_entries.return_value = [entry]

    result = resolve_entry(hass, None)

    assert result is entry


def test_resolve_entry_multiple_entries() -> None:
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = [_mock_entry("a"), _mock_entry("b")]

    result = resolve_entry(hass, None)

    assert result is None


def test_resolve_entry_no_entries() -> None:
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []

    result = resolve_entry(hass, None)

    assert result is None
