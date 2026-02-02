"""Tests for evening behavior decision engine logic."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BALANCING_INTERVAL_DAYS,
    CONF_BALANCING_PV_THRESHOLD,
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_MAX_SOC,
    CONF_PROG1_SOC_ENTITY,
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG6_SOC_ENTITY,
    CONF_PV_FORECAST_TOMORROW,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.evening_behavior import (
    async_run_evening_behavior,
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
    hass.data = {DOMAIN: {entry.entry_id: {}}}
    return hass


@pytest.mark.asyncio
async def test_evening_behavior_balancing_triggers_program_updates() -> None:
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_PROG6_SOC_ENTITY: "number.prog6_soc",
        CONF_MAX_CHARGE_CURRENT_ENTITY: "number.max_charge_current",
        CONF_PV_FORECAST_TOMORROW: "sensor.pv_forecast",
        CONF_BALANCING_INTERVAL_DAYS: 10,
        CONF_BALANCING_PV_THRESHOLD: 20.5,
        CONF_MAX_SOC: 100,
    }
    states = {
        "sensor.pv_forecast": "0",
    }
    hass = _setup_hass(config, states)

    await async_run_evening_behavior(hass, entry_id="entry-1")

    number_calls = [
        call
        for call in hass.services.async_call.call_args_list
        if call.args[0] == "number" and call.args[1] == "set_value"
    ]

    entities = {call.args[2]["entity_id"] for call in number_calls}
    assert "number.prog1_soc" in entities
    assert "number.prog2_soc" in entities
    assert "number.prog6_soc" in entities
    assert "number.max_charge_current" in entities
