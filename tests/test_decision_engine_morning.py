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
    CONF_PROG2_TIME_START_ENTITY,
    CONF_PV_EFFICIENCY,
    CONF_PV_FORECAST_SENSOR,
    CONF_HIGH_TARIFF_END_HOUR_SENSOR,
    DEFAULT_HEAT_PUMP_FORECAST_DOMAIN,
    DEFAULT_HEAT_PUMP_FORECAST_SERVICE,
    DEFAULT_PV_EFFICIENCY,
    DOMAIN,
    CONF_PV_FORECAST_TODAY,
)
from custom_components.energy_optimizer.calculations.battery import (
    calculate_charge_current,
    calculate_soc_delta,
    calculate_target_soc,
)
from custom_components.energy_optimizer.decision_engine.morning_charge import (
    MorningChargeStrategy,
    async_run_morning_charge,
)
from custom_components.energy_optimizer.decision_engine import common as decision_common
from custom_components.energy_optimizer.utils.pv_forecast import MorningPVForecast

pytestmark = pytest.mark.enable_socket


@pytest.fixture(autouse=True)
def _mock_charge_completion(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Avoid real Home Assistant storage in decision-engine unit tests."""
    schedule = AsyncMock()
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.async_schedule_charge_completion",
        schedule,
    )
    return schedule


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


def test_morning_charge_uses_uncompensated_pv_forecast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep morning PV sufficiency aligned with morning sell."""
    strategy = MorningChargeStrategy(MagicMock(), entry_id="entry-1", margin=None)
    strategy.entry = MagicMock(entry_id="entry-1")
    strategy.config = {}
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.resolve_tariff_end_hour",
        lambda *args, **kwargs: 13,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.resolve_night_buy_window_end_hour",
        lambda *args, **kwargs: 5,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.resolve_day_buy_window_start_hour",
        lambda *args, **kwargs: 12,
    )

    assert strategy._resolve_forecast_params() == (
        5,
        12,
        {"compensate": False, "use_morning_pv_fallback": True},
    )


@pytest.mark.asyncio
async def test_morning_charge_gathers_forecast_through_shared_morning_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the same validated morning parser as Morning Peak Sell."""
    parser_forecast = MorningPVForecast(
        total_kwh=2.0,
        hourly_kwh={hour: 0.0 for hour in range(5, 12)},
        status="valid_hourly",
        method="detailed_hourly",
        source_entity="sensor.pv_today",
        aggregate_kwh=2.0,
        raw_hourly_kwh=2.0,
        difference_kwh=0.0,
        tolerance_kwh=0.25,
        daylight_hours=[],
        sufficiency_available=True,
    )
    parser_calls: list[dict[str, object]] = []

    def _parser(*_args: object, **kwargs: object) -> MorningPVForecast:
        parser_calls.append(kwargs)
        return parser_forecast

    async def _heat_pump(*_args: object, **_kwargs: object) -> tuple[float, dict[int, float]]:
        return 0.0, {}

    monkeypatch.setattr(
        decision_common,
        "build_hourly_usage_array",
        lambda *_args, **_kwargs: [0.0] * 24,
    )
    monkeypatch.setattr(decision_common, "get_heat_pump_forecast_window", _heat_pump)
    monkeypatch.setattr(decision_common, "get_morning_pv_forecast", _parser)
    monkeypatch.setattr(decision_common, "calculate_losses", lambda *_args, **_kwargs: (0.0, 0.0))

    forecasts = await decision_common.gather_forecasts(
        MagicMock(),
        {CONF_PV_FORECAST_TODAY: "sensor.pv_today"},
        start_hour=5,
        end_hour=12,
        margin=1.0,
        entry_id="entry-1",
        use_morning_pv_fallback=True,
    )

    assert parser_calls == [
        {"start_hour": 5, "end_hour": 12, "apply_efficiency": True}
    ]
    assert forecasts.morning_pv_forecast is parser_forecast


@pytest.mark.asyncio
async def test_morning_charge_no_action_when_reserve_sufficient() -> None:
    config = {
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_PROG2_TIME_START_ENTITY: "time.prog2_start",
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
        "time.prog2_start": "04:00:00",
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
        CONF_PROG2_TIME_START_ENTITY: "time.prog2_start",
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_DAILY_LOAD_SENSOR: "sensor.daily_load",
        CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end_hour",
        CONF_BATTERY_CAPACITY_AH: 100,
        CONF_BATTERY_VOLTAGE: 50,
        CONF_MIN_SOC: 10,
        CONF_MAX_SOC: 100,
        CONF_BATTERY_EFFICIENCY: 100,
        CONF_TEST_MODE: False,  # Disable test mode for this test
    }
    states = {
        "number.prog2_soc": "50",
        "time.prog2_start": "04:00:00",
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
    control_calls = [
        call
        for call in hass.services.async_call.call_args_list
        if call.args[0] in ("time", "input_datetime", "number")
    ]
    assert control_calls[0].args[:2] == ("time", "set_value")
    assert control_calls[1].args[:2] == ("number", "set_value")
    assert control_calls[1].args[2]["entity_id"] == "number.prog2_soc"


@pytest.mark.asyncio
async def test_morning_charge_includes_pv_and_heat_pump_and_sets_current() -> None:
    from custom_components.energy_optimizer.const import CONF_TEST_MODE

    config = {
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_PROG2_TIME_START_ENTITY: "time.prog2_start",
        CONF_CHARGE_CURRENT_ENTITY: "number.charge_current",
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_DAILY_LOAD_SENSOR: "sensor.daily_load",
        CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end_hour",
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
        "time.prog2_start": "04:00:00",
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
        CONF_PROG2_TIME_START_ENTITY: "time.prog2_start",
        CONF_CHARGE_CURRENT_ENTITY: "number.charge_current",
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_DAILY_LOAD_SENSOR: "sensor.daily_load",
        CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end_hour",
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
        "time.prog2_start": "04:00:00",
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
        CONF_PROG2_TIME_START_ENTITY: "time.prog2_start",
        CONF_CHARGE_CURRENT_ENTITY: "number.charge_current",
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_DAILY_LOAD_SENSOR: "sensor.daily_load",
        CONF_DAILY_LOSSES_SENSOR: "sensor.daily_losses",
        CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end_hour",
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
        "time.prog2_start": "04:00:00",
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
    assert details["target_soc"] == pytest.approx(66.0)
    assert details["charge_current_a"] == pytest.approx(8)
    history_sensor = hass.data[DOMAIN]["entry-1"]["optimization_history_sensor"]
    assert history_sensor.add_entry.call_args.kwargs["windows"] == [
        ["cr", 6, "nb_e", 13, "db_s", False]
    ]


def test_calculate_soc_delta() -> None:
    soc_delta = calculate_soc_delta(3.72, capacity_ah=37, voltage=576)

    assert soc_delta == pytest.approx(17.0)


def test_calculate_target_soc() -> None:
    soc_delta = calculate_soc_delta(3.72, capacity_ah=37, voltage=576)
    target_soc = calculate_target_soc(25.0, soc_delta, max_soc=100)

    assert target_soc == pytest.approx(42.0)

    assert calculate_target_soc(80, -52, max_soc=100) == 28.0
    assert calculate_target_soc(30, -52, max_soc=100) == -22.0


def test_calculate_charge_current_rounds_up() -> None:
    current = calculate_charge_current(
        3.72,
        current_soc=25.0,
        capacity_ah=37,
        voltage=576,
    )

    assert current == 4


def test_calculate_charge_current_respects_target_charge_time_hours() -> None:
    current = calculate_charge_current(
        3.72,
        current_soc=25.0,
        capacity_ah=37,
        voltage=576,
        target_charge_time_hours=4.0,
    )

    assert current == 2


@pytest.mark.asyncio
async def test_morning_charge_uses_night_buy_window_duration_for_current_sizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.energy_optimizer.const import CONF_TEST_MODE
    from custom_components.energy_optimizer.decision_engine.common import ChargeAction

    config = {
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_PROG2_TIME_START_ENTITY: "time.prog2_start",
        CONF_CHARGE_CURRENT_ENTITY: "number.charge_current",
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_DAILY_LOAD_SENSOR: "sensor.daily_load",
        CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end_hour",
        CONF_BATTERY_CAPACITY_AH: 100,
        CONF_BATTERY_VOLTAGE: 50,
        CONF_MIN_SOC: 10,
        CONF_MAX_SOC: 100,
        CONF_BATTERY_EFFICIENCY: 100,
        CONF_TEST_MODE: False,
    }
    states = {
        "number.prog2_soc": "50",
        "time.prog2_start": "04:00:00",
        "number.charge_current": "0",
        "sensor.battery_soc": "90",
        "sensor.daily_load": "48",
        "sensor.tariff_end_hour": "13",
    }
    hass = _setup_hass(config, states)
    captured: dict[str, float] = {}

    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.resolve_night_buy_window_duration_hours",
        lambda *args, **kwargs: 4.0,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.charge_base.calculate_charge_action",
        lambda bc, **kwargs: (
            captured.update({"target_charge_time_hours": kwargs["target_charge_time_hours"]})
            or ChargeAction(
                gap_to_charge_kwh=1.0,
                soc_delta=1.0,
                target_soc=60.0,
                charge_current=2.0,
            )
        ),
    )

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    assert captured["target_charge_time_hours"] == pytest.approx(4.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_charge_current", "expected_current_calls"),
    [
        (
            "1",
            [
                ("number.max_charge_current", 23),
                ("number.charge_current", 2.0),
            ],
        ),
        ("2", [("number.charge_current", 2.0)]),
        ("3", [("number.charge_current", 2.0)]),
    ],
)
async def test_morning_charge_restores_lower_max_current_before_setting_current(
    monkeypatch: pytest.MonkeyPatch,
    max_charge_current: str,
    expected_current_calls: list[tuple[str, float]],
) -> None:
    from custom_components.energy_optimizer.const import (
        CONF_MAX_CHARGE_CURRENT_ENTITY,
        CONF_TEST_MODE,
        DEFAULT_MAX_CHARGE_CURRENT,
    )
    from custom_components.energy_optimizer.decision_engine.common import ChargeAction

    config = {
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_PROG2_TIME_START_ENTITY: "time.prog2_start",
        CONF_CHARGE_CURRENT_ENTITY: "number.charge_current",
        CONF_MAX_CHARGE_CURRENT_ENTITY: "number.max_charge_current",
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_DAILY_LOAD_SENSOR: "sensor.daily_load",
        CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end_hour",
        CONF_BATTERY_CAPACITY_AH: 100,
        CONF_BATTERY_VOLTAGE: 50,
        CONF_MIN_SOC: 10,
        CONF_MAX_SOC: 100,
        CONF_BATTERY_EFFICIENCY: 100,
        CONF_TEST_MODE: False,
    }
    states = {
        "number.prog2_soc": "50",
        "time.prog2_start": "04:00:00",
        "number.charge_current": "0",
        "number.max_charge_current": max_charge_current,
        "sensor.battery_soc": "90",
        "sensor.daily_load": "48",
        "sensor.tariff_end_hour": "13",
    }
    hass = _setup_hass(config, states)

    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.charge_base.calculate_charge_action",
        lambda *_args, **_kwargs: ChargeAction(
            gap_to_charge_kwh=1.0,
            soc_delta=1.0,
            target_soc=60.0,
            charge_current=2.0,
        ),
    )

    await async_run_morning_charge(hass, entry_id="entry-1", margin=1.0)

    current_calls = [
        (call.args[2]["entity_id"], call.args[2]["value"])
        for call in hass.services.async_call.call_args_list
        if call.args[0] == "number"
        and call.args[1] == "set_value"
        and call.args[2]["entity_id"]
        in {"number.max_charge_current", "number.charge_current"}
    ]

    assert current_calls == [
        (
            entity_id,
            DEFAULT_MAX_CHARGE_CURRENT
            if entity_id == "number.max_charge_current"
            else value,
        )
        for entity_id, value in expected_current_calls
    ]
