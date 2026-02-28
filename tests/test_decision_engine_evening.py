"""Tests for evening behavior decision engine logic."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_BALANCING_INTERVAL_DAYS,
    CONF_BALANCING_PV_THRESHOLD,
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_PROG1_SOC_ENTITY,
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG6_SOC_ENTITY,
    CONF_PV_FORECAST_TOMORROW,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.evening_behavior import (
    _calculate_preservation_context,
    _handle_preservation,
    async_run_evening_behavior,
)

pytestmark = pytest.mark.enable_socket
EVENING = "custom_components.energy_optimizer.decision_engine.evening_behavior"


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
async def test_evening_behavior_balancing_triggers_program_updates() -> None:
    from custom_components.energy_optimizer.const import CONF_TEST_MODE
    
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_PROG6_SOC_ENTITY: "number.prog6_soc",
        CONF_MAX_CHARGE_CURRENT_ENTITY: "number.max_charge_current",
        CONF_PV_FORECAST_TOMORROW: "sensor.pv_forecast",
        CONF_BALANCING_INTERVAL_DAYS: 10,
        CONF_BALANCING_PV_THRESHOLD: 20.5,
        CONF_MAX_SOC: 100,
        CONF_TEST_MODE: False,  # Disable test mode for this test
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


def _base_preservation_config() -> dict[str, object]:
    return {
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_MIN_SOC: 20,
        CONF_MAX_SOC: 100,
        CONF_BATTERY_CAPACITY_AH: 37,
        CONF_BATTERY_VOLTAGE: 640,
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG6_SOC_ENTITY: "number.prog6_soc",
        CONF_PV_FORECAST_TOMORROW: "sensor.pv_forecast",
    }


def _patch_preservation_inputs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    hourly_usage: list[float],
    heat_pump_hourly: dict[int, float],
    pv_hourly: dict[int, float],
    losses_hourly: float,
    tariff_end_hour: int = 13,
    reserve_kwh: float = 5.0,
    battery_space_kwh: float = 10.0,
) -> None:
    async def _hp(*args, **kwargs):
        return 0.0, heat_pump_hourly

    monkeypatch.setattr(
        f"{EVENING}.build_hourly_usage_array",
        lambda config, get_state, daily_load_fallback=None: hourly_usage,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        lambda *args, **kwargs: (sum(pv_hourly.values()), pv_hourly),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (losses_hourly, losses_hourly),
    )
    monkeypatch.setattr(
        f"{EVENING}.resolve_tariff_end_hour",
        lambda hass, config: tariff_end_hour,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: reserve_kwh,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_space",
        lambda *args, **kwargs: battery_space_kwh,
    )


@pytest.mark.asyncio
async def test_preservation_context_calculates_lower_morning_target_soc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_preservation_config()
    hass = _setup_hass(config, {"sensor.battery_soc": "68"})
    usage = [0.0] * 24
    usage[6] = 1.0
    usage[7] = 1.0
    usage[8] = 0.2

    _patch_preservation_inputs(
        monkeypatch,
        hourly_usage=usage,
        heat_pump_hourly={6: 0.5, 7: 0.5, 8: 0.1},
        pv_hourly={8: 2.0},
        losses_hourly=0.1,
    )

    battery_config = SimpleNamespace(
        min_soc=20.0,
        max_soc=100.0,
        capacity_ah=37.0,
        voltage=640.0,
        efficiency=90.0,
    )
    context = await _calculate_preservation_context(
        hass,
        config,
        entry_id="entry-1",
        current_soc=68.0,
        battery_config=battery_config,
        margin=1.1,
        pv_with_efficiency=20.0,
        afternoon_grid_assist_sensor=None,
    )

    assert context.sufficiency_hour == 8
    assert context.morning_target_soc < 68.0
    assert context.morning_target_soc > battery_config.min_soc


@pytest.mark.asyncio
async def test_preservation_context_empty_morning_window_uses_min_soc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_preservation_config()
    hass = _setup_hass(config, {"sensor.battery_soc": "68"})
    usage = [0.0] * 24
    usage[6] = 0.5

    _patch_preservation_inputs(
        monkeypatch,
        hourly_usage=usage,
        heat_pump_hourly={6: 0.0},
        pv_hourly={6: 1.0},
        losses_hourly=0.1,
    )

    battery_config = SimpleNamespace(
        min_soc=20.0,
        max_soc=100.0,
        capacity_ah=37.0,
        voltage=640.0,
        efficiency=90.0,
    )
    context = await _calculate_preservation_context(
        hass,
        config,
        entry_id="entry-1",
        current_soc=68.0,
        battery_config=battery_config,
        margin=1.1,
        pv_with_efficiency=20.0,
        afternoon_grid_assist_sensor=None,
    )

    assert context.sufficiency_hour == 6
    assert context.morning_target_soc == battery_config.min_soc
    assert context.morning_needed_reserve_kwh == 0.0


@pytest.mark.asyncio
async def test_preservation_context_no_sufficiency_uses_tariff_end_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_preservation_config()
    hass = _setup_hass(config, {"sensor.battery_soc": "68"})
    usage = [0.0] * 24
    for hour in range(6, 13):
        usage[hour] = 1.2

    _patch_preservation_inputs(
        monkeypatch,
        hourly_usage=usage,
        heat_pump_hourly={},
        pv_hourly={},
        losses_hourly=0.1,
        tariff_end_hour=13,
    )

    battery_config = SimpleNamespace(
        min_soc=20.0,
        max_soc=100.0,
        capacity_ah=37.0,
        voltage=640.0,
        efficiency=90.0,
    )
    context = await _calculate_preservation_context(
        hass,
        config,
        entry_id="entry-1",
        current_soc=68.0,
        battery_config=battery_config,
        margin=1.1,
        pv_with_efficiency=20.0,
        afternoon_grid_assist_sensor=None,
    )

    assert context.sufficiency_reached is False
    assert context.morning_needed_reserve_kwh > 0.0
    assert context.morning_target_soc > battery_config.min_soc


@pytest.mark.asyncio
async def test_preservation_context_clamps_morning_target_to_current_soc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_preservation_config()
    hass = _setup_hass(config, {"sensor.battery_soc": "30"})
    usage = [0.0] * 24
    usage[6] = 2.5
    usage[7] = 2.5

    _patch_preservation_inputs(
        monkeypatch,
        hourly_usage=usage,
        heat_pump_hourly={6: 1.0, 7: 1.0},
        pv_hourly={8: 1.0},
        losses_hourly=0.2,
    )

    battery_config = SimpleNamespace(
        min_soc=20.0,
        max_soc=100.0,
        capacity_ah=37.0,
        voltage=640.0,
        efficiency=90.0,
    )
    context = await _calculate_preservation_context(
        hass,
        config,
        entry_id="entry-1",
        current_soc=30.0,
        battery_config=battery_config,
        margin=1.1,
        pv_with_efficiency=20.0,
        afternoon_grid_assist_sensor=None,
    )

    assert context.morning_target_soc == 30.0


@pytest.mark.asyncio
async def test_handle_preservation_grid_assist_uses_morning_target_soc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_preservation_config()
    hass = _setup_hass(config, {"sensor.battery_soc": "68", "sensor.pv_forecast": "5"})
    entry = hass.config_entries.async_get_entry("entry-1")

    captured_outcomes = []

    async def _capture_log(hass, entry, outcome, context, logger):
        captured_outcomes.append(outcome)

    set_program_soc_mock = AsyncMock()
    monkeypatch.setattr(f"{EVENING}.set_program_soc", set_program_soc_mock)
    monkeypatch.setattr(f"{EVENING}.log_decision_unified", _capture_log)

    activated = await _handle_preservation(
        hass,
        entry,
        integration_context=MagicMock(),
        grid_assist_on=True,
        reserve_insufficient=False,
        pv_with_efficiency=50.0,
        battery_space=1.0,
        prog1_soc="number.prog1_soc",
        prog6_soc="number.prog6_soc",
        current_soc=68.0,
        morning_target_soc=35.0,
        morning_needed_reserve_kwh=3.52,
        pv_forecast=5.0,
        heat_pump_window_kwh=4.11,
        heat_pump_to_sufficiency_kwh=1.23,
        reserve_kwh=8.0,
        required_kwh=10.0,
        required_sufficiency_kwh=4.0,
        pv_sufficiency_kwh=1.0,
        needed_reserve_sufficiency_kwh=3.0,
        sufficiency_hour=8,
        sufficiency_reached=True,
        pv_forecast_window_kwh=12.0,
        pv_compensation_details={},
    )

    assert activated is True
    assert set_program_soc_mock.await_count == 2
    assert set_program_soc_mock.await_args_list[0].args[2] == 35.0
    assert set_program_soc_mock.await_args_list[1].args[2] == 35.0

    assert captured_outcomes
    details = captured_outcomes[-1].details
    assert details["current_soc"] == 68.0
    assert details["target_soc"] == 35.0
    assert details["morning_target_soc"] == 35.0
    assert details["morning_needed_reserve_kwh"] == 3.52
