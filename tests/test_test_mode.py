"""Tests for test mode behavior."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import CONF_TEST_MODE
from custom_components.energy_optimizer.controllers.inverter import set_program_soc
from custom_components.energy_optimizer.helpers import is_test_mode


def _mock_entry(*, data: dict | None = None, options: dict | None = None) -> MagicMock:
    entry = MagicMock()
    entry.data = data or {}
    entry.options = options or {}
    return entry


def test_is_test_mode_defaults_false() -> None:
    entry = _mock_entry()

    assert is_test_mode(entry) is False


def test_is_test_mode_from_data() -> None:
    entry = _mock_entry(data={CONF_TEST_MODE: True})

    assert is_test_mode(entry) is True


def test_is_test_mode_from_options_overrides_data() -> None:
    entry = _mock_entry(data={CONF_TEST_MODE: False}, options={CONF_TEST_MODE: True})

    assert is_test_mode(entry) is True


@pytest.mark.asyncio
async def test_set_program_soc_skips_when_test_mode_enabled() -> None:
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    entry = _mock_entry(data={CONF_TEST_MODE: True})

    await set_program_soc(
        hass,
        "number.prog1_soc",
        80.0,
        entry=entry,
    )

    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_set_program_soc_calls_when_test_mode_disabled() -> None:
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    entry = _mock_entry(data={CONF_TEST_MODE: False})

    await set_program_soc(
        hass,
        "number.prog1_soc",
        80.0,
        entry=entry,
    )

    hass.services.async_call.assert_called_once()
