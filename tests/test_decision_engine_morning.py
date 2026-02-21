"""Tests for morning decision engine logic."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_CHARGE_CURRENT_ENTITY,
    CONF_DAILY_LOAD_SENSOR,
    CONF_ENABLE_HEAT_PUMP,
    CONF_HEAT_PUMP_FORECAST_DOMAIN,
    CONF_HEAT_PUMP_FORECAST_SERVICE,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_PROG2_SOC_ENTITY,
    CONF_PV_EFFICIENCY,
    CONF_PV_FORECAST_SENSOR,
    CONF_TARIFF_END_HOUR_SENSOR,
    DEFAULT_HEAT_PUMP_FORECAST_DOMAIN,
    DEFAULT_HEAT_PUMP_FORECAST_SERVICE,
    DEFAULT_PV_EFFICIENCY,
    DOMAIN,
)
from custom_components.energy_optimizer.calculations.battery import (
    calculate_charge_current,
    calculate_soc_delta,
    calculate_target_soc,
)
from custom_components.energy_optimizer.decision_engine.morning_charge import (
    async_run_morning_charge,
)

pytestmark = pytest.mark.enable_socket


def _state(value: str | tuple[str, dict[str, object]]) -> MagicMock:
    state = MagicMock()
    if isinstance(value, tuple):
        state.state = value[0]
        state.attributes = value[1]
    else:
        state.state = value
        state.attributes = {}
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
    hass.services.has_service = MagicMock(return_value=False)
    
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
        CONF_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end_hour",
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
        "sensor.tariff_end_hour": "13",
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


@pytest.mark.asyncio
async def test_morning_charge_includes_pv_and_heat_pump_and_sets_current() -> None:
    from custom_components.energy_optimizer.const import CONF_TEST_MODE

    config = {
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_CHARGE_CURRENT_ENTITY: "number.charge_current",
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_DAILY_LOAD_SENSOR: "sensor.daily_load",
        CONF_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end_hour",
        CONF_PV_FORECAST_SENSOR: "sensor.pv_forecast",
        CONF_PV_EFFICIENCY: DEFAULT_PV_EFFICIENCY,
        CONF_ENABLE_HEAT_PUMP: True,
        CONF_HEAT_PUMP_FORECAST_DOMAIN: DEFAULT_HEAT_PUMP_FORECAST_DOMAIN,
        CONF_HEAT_PUMP_FORECAST_SERVICE: DEFAULT_HEAT_PUMP_FORECAST_SERVICE,
        CONF_BATTERY_CAPACITY_AH: 100,
        CONF_BATTERY_VOLTAGE: 50,
        CONF_MIN_SOC: 10,
        CONF_MAX_SOC: 100,
        CONF_BATTERY_EFFICIENCY: 100,
        CONF_TEST_MODE: False,
    }
    pv_forecast = (
        "0",
        {
            "detailedForecast": [
                {"period_start": "2026-02-06T06:00:00+01:00", "pv_estimate": 0.5},
                {"period_start": "2026-02-06T06:30:00+01:00", "pv_estimate": 0.5},
                {"period_start": "2026-02-06T07:00:00+01:00", "pv_estimate": 1.0},
            ]
        },
    )
    states = {
        "number.prog2_soc": "50",
        "number.charge_current": "0",
        "sensor.battery_soc": "20",
        "sensor.daily_load": "48",
        "sensor.tariff_end_hour": "8",
        "sensor.pv_forecast": pv_forecast,
    }
    hass = _setup_hass(config, states)

    hass.services.has_service.return_value = True

    async def _service_call(domain: str, service: str, data: dict, **kwargs):
        if domain == DEFAULT_HEAT_PUMP_FORECAST_DOMAIN and service == DEFAULT_HEAT_PUMP_FORECAST_SERVICE:
            return {"total_energy_kwh": 6.0}
        return None

    hass.services.async_call = AsyncMock(side_effect=_service_call)

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    number_calls = [
        call
        for call in hass.services.async_call.call_args_list
        if call.args[0] == "number" and call.args[1] == "set_value"
    ]
    assert any(call.args[2]["entity_id"] == "number.prog2_soc" for call in number_calls)
    assert any(
        call.args[2]["entity_id"] == "number.charge_current" for call in number_calls
    )


@pytest.mark.asyncio
async def test_morning_charge_uses_sufficiency_deficit_when_pv_ramps_late() -> None:
    from custom_components.energy_optimizer.const import CONF_TEST_MODE

    config = {
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_CHARGE_CURRENT_ENTITY: "number.charge_current",
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_DAILY_LOAD_SENSOR: "sensor.daily_load",
        CONF_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end_hour",
        CONF_PV_FORECAST_SENSOR: "sensor.pv_forecast",
        CONF_PV_EFFICIENCY: DEFAULT_PV_EFFICIENCY,
        CONF_ENABLE_HEAT_PUMP: True,
        CONF_HEAT_PUMP_FORECAST_DOMAIN: DEFAULT_HEAT_PUMP_FORECAST_DOMAIN,
        CONF_HEAT_PUMP_FORECAST_SERVICE: DEFAULT_HEAT_PUMP_FORECAST_SERVICE,
        CONF_BATTERY_CAPACITY_AH: 100,
        CONF_BATTERY_VOLTAGE: 50,
        CONF_MIN_SOC: 20,
        CONF_MAX_SOC: 100,
        CONF_BATTERY_EFFICIENCY: 100,
        CONF_TEST_MODE: False,
    }
    pv_forecast = (
        "0",
        {
            "detailedForecast": [
                {"period_start": "2026-02-06T09:00:00+01:00", "pv_estimate": 5.0},
            ]
        },
    )
    states = {
        "number.prog2_soc": "50",
        "number.charge_current": "0",
        "sensor.battery_soc": "20",
        "sensor.daily_load": "24",
        "sensor.tariff_end_hour": "10",
        "sensor.pv_forecast": pv_forecast,
    }
    hass = _setup_hass(config, states)

    hass.services.has_service.return_value = True

    async def _service_call(domain: str, service: str, data: dict, **kwargs):
        if (
            domain == DEFAULT_HEAT_PUMP_FORECAST_DOMAIN
            and service == DEFAULT_HEAT_PUMP_FORECAST_SERVICE
        ):
            return {
                "total_energy_kwh": 0.0,
                "hours": [
                    {"datetime": "2026-02-06T06:00:00+01:00", "energy_kwh": 0.0},
                    {"datetime": "2026-02-06T07:00:00+01:00", "energy_kwh": 0.0},
                    {"datetime": "2026-02-06T08:00:00+01:00", "energy_kwh": 0.0},
                    {"datetime": "2026-02-06T09:00:00+01:00", "energy_kwh": 0.0},
                ],
            }
        return None

    hass.services.async_call = AsyncMock(side_effect=_service_call)

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    number_calls = [
        call
        for call in hass.services.async_call.call_args_list
        if call.args[0] == "number" and call.args[1] == "set_value"
    ]
    assert any(call.args[2]["entity_id"] == "number.prog2_soc" for call in number_calls)
    assert any(
        call.args[2]["entity_id"] == "number.charge_current" for call in number_calls
    )


@pytest.mark.asyncio
async def test_morning_charge_logs_last_optimization_attributes() -> None:
    from custom_components.energy_optimizer.const import CONF_DAILY_LOSSES_SENSOR, CONF_TEST_MODE

    config = {
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_CHARGE_CURRENT_ENTITY: "number.charge_current",
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_DAILY_LOAD_SENSOR: "sensor.daily_load",
        CONF_DAILY_LOSSES_SENSOR: "sensor.daily_losses",
        CONF_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end_hour",
        CONF_PV_FORECAST_SENSOR: "sensor.pv_forecast",
        CONF_PV_EFFICIENCY: DEFAULT_PV_EFFICIENCY,
        CONF_ENABLE_HEAT_PUMP: True,
        CONF_HEAT_PUMP_FORECAST_DOMAIN: DEFAULT_HEAT_PUMP_FORECAST_DOMAIN,
        CONF_HEAT_PUMP_FORECAST_SERVICE: DEFAULT_HEAT_PUMP_FORECAST_SERVICE,
        CONF_BATTERY_CAPACITY_AH: 37,
        CONF_BATTERY_VOLTAGE: 576,
        CONF_MIN_SOC: 15,
        CONF_MAX_SOC: 100,
        CONF_BATTERY_EFFICIENCY: 95,
        CONF_TEST_MODE: False,
    }
    pv_forecast = (
        "0",
        {
            "detailedForecast": [
                {"period_start": "2026-02-07T06:00:00+01:00", "pv_estimate": 0.62},
                {"period_start": "2026-02-07T07:00:00+01:00", "pv_estimate": 0.62},
                {"period_start": "2026-02-07T08:00:00+01:00", "pv_estimate": 0.62},
                {"period_start": "2026-02-07T09:00:00+01:00", "pv_estimate": 0.62},
                {"period_start": "2026-02-07T10:00:00+01:00", "pv_estimate": 0.62},
                {"period_start": "2026-02-07T11:00:00+01:00", "pv_estimate": 0.62},
                {"period_start": "2026-02-07T12:00:00+01:00", "pv_estimate": 0.6},
            ]
        },
    )
    states = {
        "number.prog2_soc": "50",
        "number.charge_current": "0",
        "sensor.battery_soc": "25",
        "sensor.daily_load": "9.4536",
        "sensor.daily_losses": "3.9273",
        "sensor.tariff_end_hour": "13",
        "sensor.pv_forecast": pv_forecast,
    }
    hass = _setup_hass(config, states)

    hass.services.has_service.return_value = True

    async def _service_call(domain: str, service: str, data: dict, **kwargs):
        if (
            domain == DEFAULT_HEAT_PUMP_FORECAST_DOMAIN
            and service == DEFAULT_HEAT_PUMP_FORECAST_SERVICE
        ):
            return {
                "total_energy_kwh": 5.17,
                "hours": [
                    {"datetime": "2026-02-07T06:00:00+01:00", "energy_kwh": 0.74},
                    {"datetime": "2026-02-07T07:00:00+01:00", "energy_kwh": 0.74},
                    {"datetime": "2026-02-07T08:00:00+01:00", "energy_kwh": 0.74},
                    {"datetime": "2026-02-07T09:00:00+01:00", "energy_kwh": 0.74},
                    {"datetime": "2026-02-07T10:00:00+01:00", "energy_kwh": 0.74},
                    {"datetime": "2026-02-07T11:00:00+01:00", "energy_kwh": 0.74},
                    {"datetime": "2026-02-07T12:00:00+01:00", "energy_kwh": 0.73},
                ],
            }
        return None

    hass.services.async_call = AsyncMock(side_effect=_service_call)

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.1)

    opt_sensor = hass.data[DOMAIN]["entry-1"]["last_optimization_sensor"]
    opt_sensor.log_optimization.assert_called_once()
    scenario, details = opt_sensor.log_optimization.call_args.args

    assert scenario == "Morning Grid Charge"
    assert details["target_soc"] == pytest.approx(68.0)
    assert "charge_current_a" not in details


def test_calculate_soc_delta() -> None:
    soc_delta = calculate_soc_delta(3.72, capacity_ah=37, voltage=576)

    assert soc_delta == pytest.approx(17.454954954954953, rel=1e-3)


def test_calculate_target_soc() -> None:
    soc_delta = calculate_soc_delta(3.72, capacity_ah=37, voltage=576)
    target_soc = calculate_target_soc(25.0, soc_delta, max_soc=100)

    assert target_soc == pytest.approx(43.0)


def test_calculate_charge_current_rounds_up() -> None:
    current = calculate_charge_current(
        3.72,
        current_soc=25.0,
        capacity_ah=37,
        voltage=576,
    )

    assert current == 4
