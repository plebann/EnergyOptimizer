"""Tests for morning decision engine logic."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_DAILY_LOAD_SENSOR,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_PROG2_SOC_ENTITY,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.morning_charge import (
    async_run_morning_charge,
)

pytestmark = pytest.mark.enable_socket


def _state(value: str) -> MagicMock:
    state = MagicMock()
    state.state = value
    return state


def _setup_hass(config: dict[str, object], states: dict[str, str]) -> MagicMock:
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.domain = DOMAIN
    entry.data = config
    hass.config_entries.async_entries.return_value = [entry]
    hass.config_entries.async_get_entry.return_value = entry
    hass.states.get.side_effect = lambda entity_id: (
        _state(states[entity_id]) if entity_id in states else None
    )
    hass.services.async_call = AsyncMock()
    
    # Mock sensors for unified logging
    mock_opt_sensor = MagicMock()
    mock_opt_sensor.log_optimization = MagicMock()
    mock_hist_sensor = MagicMock()
    mock_hist_sensor.add_entry = MagicMock()
    
    # Mock bus for custom events
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                "last_optimization_sensor": mock_opt_sensor,
                "optimization_history_sensor": mock_hist_sensor,
            }
        }
    }
    return hass


@pytest.mark.asyncio
async def test_morning_charge_no_action_when_reserve_sufficient() -> None:
    config = {
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_DAILY_LOAD_SENSOR: "sensor.daily_load",
        CONF_BATTERY_CAPACITY_AH: 100,
        CONF_BATTERY_VOLTAGE: 50,
        CONF_MIN_SOC: 10,
        CONF_MAX_SOC: 100,
        CONF_BATTERY_EFFICIENCY: 100,
    }
    states = {
        "number.prog2_soc": "50",
        "sensor.battery_soc": "90",
        "sensor.daily_load": "12",
    }
    hass = _setup_hass(config, states)

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    number_calls = [
        call
        for call in hass.services.async_call.call_args_list
        if call.args[0] == "number"
    ]
    assert number_calls == []


@pytest.mark.asyncio
async def test_morning_charge_sets_program_when_deficit() -> None:
    from custom_components.energy_optimizer.const import CONF_TEST_MODE
    
    config = {
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_DAILY_LOAD_SENSOR: "sensor.daily_load",
        CONF_BATTERY_CAPACITY_AH: 100,
        CONF_BATTERY_VOLTAGE: 50,
        CONF_MIN_SOC: 10,
        CONF_MAX_SOC: 100,
        CONF_BATTERY_EFFICIENCY: 100,
        CONF_TEST_MODE: False,  # Disable test mode for this test
    }
    states = {
        "number.prog2_soc": "50",
        "sensor.battery_soc": "90",
        "sensor.daily_load": "48",
    }
    hass = _setup_hass(config, states)

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    number_calls = [
        call
        for call in hass.services.async_call.call_args_list
        if call.args[0] == "number" and call.args[1] == "set_value"
    ]
    assert number_calls
    assert any(
        call.args[2]["entity_id"] == "number.prog2_soc" for call in number_calls
    )
