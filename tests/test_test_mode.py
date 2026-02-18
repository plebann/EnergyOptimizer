"""Tests for test mode behavior."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import CONF_TEST_MODE, DOMAIN
from custom_components.energy_optimizer.controllers.inverter import set_program_soc
from custom_components.energy_optimizer.helpers import is_test_mode
from custom_components.energy_optimizer.switch import (
    TestModeSwitch as EnergyOptimizerTestModeSwitch,
)
from custom_components.energy_optimizer.switch import async_setup_entry


def _mock_entry(*, data: dict | None = None, options: dict | None = None) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = data or {}
    entry.options = options or {}
    return entry


def test_is_test_mode_defaults_false() -> None:
    hass = MagicMock()
    hass.data = {}
    entry = _mock_entry()

    assert is_test_mode(hass, entry) is False


def test_is_test_mode_from_switch() -> None:
    hass = MagicMock()
    entry = _mock_entry(data={CONF_TEST_MODE: True})
    test_mode_switch = MagicMock()
    test_mode_switch.is_on = False
    hass.data = {DOMAIN: {entry.entry_id: {"test_mode_switch": test_mode_switch}}}

    assert is_test_mode(hass, entry) is False


def test_is_test_mode_fallback_from_data() -> None:
    hass = MagicMock()
    hass.data = {DOMAIN: {"other-entry": {}}}
    entry = _mock_entry(data={CONF_TEST_MODE: True})

    assert is_test_mode(hass, entry) is True


@pytest.mark.asyncio
async def test_set_program_soc_skips_when_test_mode_enabled() -> None:
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    entry = _mock_entry(data={CONF_TEST_MODE: False})
    test_mode_switch = MagicMock()
    test_mode_switch.is_on = True
    hass.data = {DOMAIN: {entry.entry_id: {"test_mode_switch": test_mode_switch}}}

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
    entry = _mock_entry(data={CONF_TEST_MODE: True})
    test_mode_switch = MagicMock()
    test_mode_switch.is_on = False
    hass.data = {DOMAIN: {entry.entry_id: {"test_mode_switch": test_mode_switch}}}

    await set_program_soc(
        hass,
        "number.prog1_soc",
        80.0,
        entry=entry,
    )

    hass.services.async_call.assert_called_once()


@pytest.mark.asyncio
async def test_switch_setup_registers_test_mode_switch() -> None:
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    entry = _mock_entry()
    added_entities: list[object] = []

    def _add_entities(entities: list[object]) -> None:
        added_entities.extend(entities)

    await async_setup_entry(hass, entry, _add_entities)

    assert len(added_entities) == 1
    assert isinstance(added_entities[0], EnergyOptimizerTestModeSwitch)
    assert "test_mode_switch" in hass.data[DOMAIN][entry.entry_id]


@pytest.mark.asyncio
async def test_test_mode_switch_restores_last_state() -> None:
    entry = _mock_entry(data={CONF_TEST_MODE: False})
    test_mode_switch = EnergyOptimizerTestModeSwitch(entry)
    last_state = MagicMock()
    last_state.state = "on"
    test_mode_switch.async_get_last_state = AsyncMock(return_value=last_state)

    await test_mode_switch.async_added_to_hass()

    assert test_mode_switch.is_on is True


@pytest.mark.asyncio
async def test_test_mode_switch_migrates_legacy_flag_without_restored_state() -> None:
    entry = _mock_entry(data={CONF_TEST_MODE: True})
    test_mode_switch = EnergyOptimizerTestModeSwitch(entry)
    test_mode_switch.async_get_last_state = AsyncMock(return_value=None)

    await test_mode_switch.async_added_to_hass()

    assert test_mode_switch.is_on is True


@pytest.mark.asyncio
async def test_test_mode_switch_turn_on_turn_off() -> None:
    entry = _mock_entry(data={CONF_TEST_MODE: False})
    test_mode_switch = EnergyOptimizerTestModeSwitch(entry)
    test_mode_switch.async_write_ha_state = MagicMock()

    await test_mode_switch.async_turn_on()
    assert test_mode_switch.is_on is True

    await test_mode_switch.async_turn_off()
    assert test_mode_switch.is_on is False

    assert test_mode_switch.async_write_ha_state.call_count == 2
