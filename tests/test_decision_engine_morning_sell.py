"""Tests for morning sell decision engine logic."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_BUY_PRICE_SENSOR,
    CONF_DISCHARGE_CURRENT_ENTITY,
    CONF_EVENING_MAX_PRICE_SENSOR,
    CONF_EXPORT_POWER_ENTITY,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_MIN_SOC,
    CONF_MIN_SOC_PV,
    CONF_MORNING_SELL_PV_COVERAGE_MARGIN,
    CONF_MORNING_MAX_PRICE_SENSOR,
    CONF_PROG3_SOC_ENTITY,
    CONF_PV_FORECAST_TODAY,
    CONF_PV_PRODUCTION_SENSOR,
    CONF_TEST_MODE,
    CONF_WORK_MODE_ENTITY,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.morning_sell import (
    MorningSellStrategy,
    async_run_morning_sell,
)
from custom_components.energy_optimizer.calculations.price_windows import ArbitrageBuyHourResult
from custom_components.energy_optimizer.utils.pv_forecast import MorningPVForecast

pytestmark = pytest.mark.enable_socket

SELL_BASE = "custom_components.energy_optimizer.decision_engine.sell_base"
MORNING = "custom_components.energy_optimizer.decision_engine.morning_sell"
HELPERS = "custom_components.energy_optimizer.helpers"


def _state(value: str) -> MagicMock:
    state = MagicMock()
    if isinstance(value, tuple):
        state.state, state.attributes = value
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
    entry.options = {}
    hass.config_entries.async_entries.return_value = [entry]
    hass.config_entries.async_get_entry.return_value = entry
    hass.states.get.side_effect = lambda entity_id: (
        _state(states[entity_id]) if entity_id in states else None
    )
    hass.services.async_call = AsyncMock()

    mock_opt_sensor = MagicMock()
    mock_opt_sensor.log_optimization = MagicMock()
    mock_hist_sensor = MagicMock()
    mock_hist_sensor.add_entry = MagicMock()

    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()

    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                "last_optimization_sensor": mock_opt_sensor,
                "optimization_history_sensor": mock_hist_sensor,
                "battery_space_sensor": SimpleNamespace(
                    entity_id="sensor.energy_optimizer_battery_space"
                ),
            }
        }
    }
    return hass


def _base_config() -> dict[str, object]:
    return {
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_PROG3_SOC_ENTITY: "number.prog3_soc",
        CONF_MORNING_MAX_PRICE_SENSOR: "sensor.morning_price",
        CONF_EVENING_MAX_PRICE_SENSOR: "sensor.evening_price",
        CONF_MIN_ARBITRAGE_PRICE: 400.0,
        CONF_WORK_MODE_ENTITY: "select.work_mode",
        CONF_EXPORT_POWER_ENTITY: "number.export_power",
        CONF_DISCHARGE_CURRENT_ENTITY: "number.discharge_current",
        CONF_PV_PRODUCTION_SENSOR: "sensor.pv_today",
        CONF_PV_FORECAST_TODAY: "sensor.pv_forecast_today",
        CONF_MORNING_SELL_PV_COVERAGE_MARGIN: 0.5,
        CONF_BATTERY_CAPACITY_AH: 37,
        CONF_BATTERY_VOLTAGE: 640,
        CONF_BATTERY_EFFICIENCY: 0.9,
        CONF_MIN_SOC: 20,
        CONF_MIN_SOC_PV: 12,
        CONF_TEST_MODE: False,
    }


def _base_states() -> dict[str, str]:
    return {
        "sensor.battery_soc": "90",
        "number.prog3_soc": "50",
        "sensor.morning_price": "250",
        "sensor.evening_price": "200",
        "sensor.pv_today": "8",
        "number.discharge_current": ("12", {"max": 30}),
        "sensor.pv_forecast_today": "2",
        "sensor.energy_optimizer_battery_space": "3",
        "sensor.morning_sell_buy_reference_internal": ("08:00", {"price": 50.0}),
    }


def _patch_common(monkeypatch: pytest.MonkeyPatch, outcomes: list) -> None:
    async def _capture_log(hass, entry, outcome, context, logger):
        outcomes.append(outcome)

    class _FakeStore:
        def __init__(self, *args, **kwargs):
            pass

        async def async_load(self):
            return None

        async def async_save(self, data):
            return None

    monkeypatch.setattr(
        f"{SELL_BASE}.log_decision_unified",
        _capture_log,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.Store",
        _FakeStore,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.set_work_mode",
        AsyncMock(),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.set_program_soc",
        AsyncMock(),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.set_export_power",
        AsyncMock(),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.set_discharge_current",
        AsyncMock(),
    )
    monkeypatch.setattr(
        f"{MORNING}.get_morning_pv_forecast",
        lambda *_args, **_kwargs: MorningPVForecast(
            total_kwh=2.0,
            hourly_kwh={hour: 0.0 for hour in range(24)},
            status="valid_hourly",
            method="hourly",
            source_entity="sensor.pv_forecast_today",
            aggregate_kwh=2.0,
            raw_hourly_kwh=2.0,
            difference_kwh=0.0,
            tolerance_kwh=0.25,
            daylight_hours=[],
            sufficiency_available=True,
        ),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.dt_util.utcnow",
        lambda: datetime(2026, 2, 24, 7, 0, 0),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.dt_util.as_local",
        lambda _dt: SimpleNamespace(hour=7),
    )
    monkeypatch.setattr(
        f"{MORNING}.build_hourly_usage_array",
        lambda config, get_state, daily_load_fallback=None: [0.0] * 24,
    )
    monkeypatch.setattr(
        f"{MORNING}.resolve_tariff_end_hour",
        lambda hass, config, default_hour=13: 13,
    )
    monkeypatch.setattr(
        f"{HELPERS}.get_internal_sensor_entity_id",
        lambda _hass, *, entry_id, unique_id_suffix, entity_domain="sensor": (
            "sensor.morning_sell_buy_reference_internal"
            if unique_id_suffix == "morning_sell_buy_reference"
            else None
        ),
    )


@pytest.mark.asyncio
async def test_morning_sell_executes_with_surplus_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.morning_price"] = "100"
    states["sensor.evening_price"] = "50"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{MORNING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (3.0, 2.0, 1.0, 13, False),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: 5.0,
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"


@pytest.mark.asyncio
async def test_morning_sell_uses_full_surplus_when_margin_gate_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.morning_price"] = "500"
    states["sensor.evening_price"] = "100"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(f"{MORNING}.get_heat_pump_forecast_window", _hp)
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (3.0, 2.0, 1.0, 13, False),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: 5.0,
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].details["selected_surplus_kwh"] == 5.0
    assert outcomes[-1].details["arbitrage_reason"] == "enabled"


@pytest.mark.asyncio
async def test_morning_sell_uses_first_qualifying_buy_hour_as_demand_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_BUY_PRICE_SENSOR] = "sensor.buy_price"
    states = _base_states()
    states["sensor.morning_price"] = "500"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    local_now = datetime(2026, 2, 24, 7, tzinfo=timezone.utc)
    monkeypatch.setattr(f"{MORNING}.dt_util.as_local", lambda _dt: local_now)
    monkeypatch.setattr(f"{MORNING}.get_buy_price_payload", lambda *args, **kwargs: [{}])
    monkeypatch.setattr(f"{MORNING}.get_internal_window_price", lambda *args, **kwargs: 50.0)
    bounds: dict[str, object] = {}

    def _find(_prices, _entity_id, **kwargs):
        bounds["start"] = kwargs["start_local"]
        bounds["end"] = kwargs["end_local"]
        bounds["max_buy_price"] = kwargs["max_buy_price"]
        return ArbitrageBuyHourResult(
            datetime(2026, 2, 24, 10, tzinfo=timezone.utc),
            50.0,
            450.0,
            "enabled",
        )

    monkeypatch.setattr(f"{MORNING}.find_first_arbitrage_buy_hour", _find)
    monkeypatch.setattr(f"{MORNING}.get_heat_pump_forecast_window", AsyncMock(return_value=(1.0, {})))
    monkeypatch.setattr(f"{MORNING}.get_pv_forecast_window", lambda *args, **kwargs: (2.0, {}))
    monkeypatch.setattr(f"{MORNING}.calculate_losses", lambda *args, **kwargs: (0.0, 0.0))
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (3.0, 2.0, 1.0, 12, True),
    )
    monkeypatch.setattr(f"{MORNING}.calculate_battery_reserve", lambda *args, **kwargs: 10.0)
    monkeypatch.setattr(f"{MORNING}.calculate_surplus_energy", lambda *args, **kwargs: 5.0)

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert bounds["start"].hour == 8
    assert bounds["end"].hour == 13
    assert bounds["max_buy_price"] == 60.0
    assert outcomes[-1].details["sell_horizon_mode"] == "arbitrage"
    assert outcomes[-1].details["selected_end_hour"] == 10
    assert outcomes[-1].details["buy_window_reference_price"] == 50.0
    assert outcomes[-1].details["buy_window_price_limit"] == 60.0
    assert outcomes[-1].history_windows == [["sr", 8, "next_h", 10, "arb_b", False]]


@pytest.mark.asyncio
async def test_morning_sell_uses_pv_sufficiency_when_day_buy_reference_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_BUY_PRICE_SENSOR] = "sensor.buy_price"
    hass = _setup_hass(config, _base_states())
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    monkeypatch.setattr(f"{MORNING}.get_buy_price_payload", lambda *args, **kwargs: [{}])
    monkeypatch.setattr(
        f"{MORNING}.get_internal_window_price",
        lambda *args, **kwargs: (
            None if kwargs["unique_id_suffix"] == "day_buy_window" else 250.0
        ),
    )
    monkeypatch.setattr(
        f"{MORNING}.find_first_arbitrage_buy_hour",
        lambda *args, **kwargs: pytest.fail("Arbitrage lookup must not run without reference"),
    )
    monkeypatch.setattr(
        f"{MORNING}.get_heat_pump_forecast_window",
        AsyncMock(return_value=(1.0, {})),
    )
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(f"{MORNING}.calculate_losses", lambda *args, **kwargs: (0.0, 0.0))
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (3.0, 2.0, 1.0, 10, True),
    )
    monkeypatch.setattr(f"{MORNING}.calculate_battery_reserve", lambda *args, **kwargs: 10.0)
    monkeypatch.setattr(f"{MORNING}.calculate_surplus_energy", lambda *args, **kwargs: 5.0)

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes[-1].details["sell_horizon_mode"] == "pv_sufficiency"
    assert outcomes[-1].details["arbitrage_reason"] == "missing_buy_window_reference"
    assert outcomes[-1].details["buy_window_reference_price"] is None
    assert outcomes[-1].details["buy_window_price_limit"] is None


@pytest.mark.asyncio
async def test_morning_sell_without_sufficiency_or_margin_sells_sunset_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.morning_price"] = "100"
    states["sensor.evening_price"] = "150"
    states["sensor.energy_optimizer_battery_space"] = "3"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{MORNING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (3.0, 2.0, 1.0, 13, False),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: 5.0,
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"
    assert outcomes[-1].details["surplus_selection_reason"] == "surplus_to_sunset_above_free_space"
    assert outcomes[-1].details["selected_surplus_kwh"] == 2.0


@pytest.mark.asyncio
async def test_morning_sell_surplus_below_free_space_and_to_22_not_above_no_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.energy_optimizer_battery_space"] = "8"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{MORNING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (3.0, 2.0, 1.0, kwargs["end_hour"], False),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    surplus_calls = iter([5.0, 6.0])
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: next(surplus_calls),
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert outcomes[-1].details["surplus_selection_reason"] == "surplus_to_sunset_not_above_free_space"


@pytest.mark.asyncio
async def test_morning_sell_surplus_below_free_space_and_to_22_above_sells_min_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.energy_optimizer_battery_space"] = "8"
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{MORNING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (3.0, 2.0, 1.0, kwargs["end_hour"], False),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    surplus_calls = iter([5.0, 9.5])
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: next(surplus_calls),
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"
    assert outcomes[-1].details["selected_surplus_kwh"] == 1.5
    assert outcomes[-1].details["surplus_selection_reason"] == "surplus_to_sunset_above_free_space"


@pytest.mark.asyncio
async def test_morning_sell_no_surplus_no_action(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{MORNING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        lambda *args, **kwargs: (1.0, {}),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (3.0, 2.0, 1.0, 13, False),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 3.0,
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: 0.0,
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert "No eligible surplus energy" in (outcomes[-1].reason or "")


@pytest.mark.asyncio
async def test_morning_sell_uses_pv_sufficiency_as_demand_window_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {8: 1.0, 9: 1.0, 10: 1.0, 11: 1.0, 12: 1.0}

    def _pv(*args, **kwargs):
        return 5.0, {8: 0.5, 9: 1.0, 10: 1.0, 11: 1.0, 12: 1.5}

    monkeypatch.setattr(
        f"{MORNING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        _pv,
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (5.0, 2.0, 1.0, 10, True),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    captured_surplus_inputs: list[tuple[float, float, float]] = []

    def _surplus(reserve: float, required: float, pv: float) -> float:
        captured_surplus_inputs.append((reserve, required, pv))
        return max(reserve + pv - required, 0.0)

    monkeypatch.setattr(f"{MORNING}.calculate_surplus_energy", _surplus)

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"
    assert outcomes[-1].details["end_hour"] == 10
    assert outcomes[-1].details["sell_horizon_mode"] == "pv_sufficiency"
    assert outcomes[-1].details["sufficiency_hour"] == 10
    assert captured_surplus_inputs == [(10.0, 1.0, 2.0)]
    assert outcomes[-1].details["base_required_kwh_full"] == 1.0
    assert outcomes[-1].details["base_pv_forecast_kwh_full"] == 2.0
    assert outcomes[-1].details["required_sufficiency_kwh"] == 2.0
    assert outcomes[-1].details["pv_sufficiency_kwh"] == 1.0


@pytest.mark.asyncio
async def test_morning_sell_uses_min_soc_pv_for_reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    captured: dict[str, float] = {}

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(f"{MORNING}.get_heat_pump_forecast_window", _hp)
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        lambda *args, **kwargs: (1.0, {}),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (3.0, 2.0, 1.0, 13, False),
    )

    def _capture_reserve(current_soc, min_soc, *args, **kwargs):
        captured["min_soc"] = min_soc
        return 3.0

    monkeypatch.setattr(f"{MORNING}.calculate_battery_reserve", _capture_reserve)
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: 0.0,
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert captured["min_soc"] == 12.0


@pytest.mark.asyncio
async def test_morning_sell_skips_when_required_reserve_exceeds_current_soc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.battery_soc"] = "50"
    hass = _setup_hass(config, states)
    outcomes: list = []

    set_work_mode = AsyncMock()
    set_program_soc = AsyncMock()
    set_export_power = AsyncMock()

    async def _capture_log(hass, entry, outcome, context, logger):
        outcomes.append(outcome)

    class _FakeStore:
        def __init__(self, *args, **kwargs):
            pass

        async def async_load(self):
            return None

        async def async_save(self, data):
            return None

    monkeypatch.setattr(f"{SELL_BASE}.log_decision_unified", _capture_log)
    monkeypatch.setattr(f"{SELL_BASE}.Store", _FakeStore)
    monkeypatch.setattr(f"{SELL_BASE}.set_work_mode", set_work_mode)
    monkeypatch.setattr(f"{SELL_BASE}.set_program_soc", set_program_soc)
    monkeypatch.setattr(f"{SELL_BASE}.set_export_power", set_export_power)
    monkeypatch.setattr(
        f"{MORNING}.get_morning_pv_forecast",
        lambda *_args, **_kwargs: MorningPVForecast(
            total_kwh=2.0,
            hourly_kwh={hour: 0.0 for hour in range(24)},
            status="valid_hourly",
            method="hourly",
            source_entity="sensor.pv_forecast_today",
            aggregate_kwh=2.0,
            raw_hourly_kwh=2.0,
            difference_kwh=0.0,
            tolerance_kwh=0.25,
            daylight_hours=[],
            sufficiency_available=True,
        ),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.dt_util.utcnow",
        lambda: datetime(2026, 2, 24, 7, 0, 0),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.dt_util.as_local",
        lambda _dt: SimpleNamespace(hour=7),
    )
    monkeypatch.setattr(
        f"{MORNING}.build_hourly_usage_array",
        lambda config, get_state, daily_load_fallback=None: [0.0] * 24,
    )
    monkeypatch.setattr(
        f"{MORNING}.resolve_tariff_end_hour",
        lambda hass, config, default_hour=13: 13,
    )

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(f"{MORNING}.get_heat_pump_forecast_window", _hp)
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (3.0, 2.0, 1.0, 13, False),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: 8.0,
    )
    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"
    set_program_soc.assert_awaited()


def test_morning_sell_discharge_current_uses_ceiling_and_entity_max() -> None:
    """Current regulator converts final sell energy to whole amps."""
    state = MagicMock()
    state.state = "8"
    state.attributes = {"max": 9}
    hass = MagicMock()
    hass.states.get.return_value = state
    strategy = MorningSellStrategy(hass, entry_id="entry-1", margin=None)
    strategy.config = {
        CONF_DISCHARGE_CURRENT_ENTITY: "number.discharge_current",
        CONF_BATTERY_VOLTAGE_SENSOR: "sensor.battery_voltage",
    }
    strategy.battery_config = SimpleNamespace(voltage=640.0)
    strategy._use_discharge_current = True
    strategy._regulator_diagnostics = {}

    voltage_state = MagicMock()
    voltage_state.state = "600"
    voltage_state.attributes = {}
    hass.states.get.side_effect = lambda entity_id: (
        state if entity_id == "number.discharge_current" else voltage_state
    )

    regulator = strategy._resolve_sell_regulator(5.1)

    assert regulator.kind == "discharge_current"
    assert regulator.entity_id == "number.discharge_current"
    assert regulator.previous_value == 8.0
    assert regulator.value == 9.0


def test_morning_sell_discharge_current_honors_zero_entity_maximum() -> None:
    """A zero maximum is a valid clamp, not a missing entity attribute."""
    state = MagicMock()
    state.state = "8"
    state.attributes = {"max": 0}
    hass = MagicMock()
    hass.states.get.return_value = state
    strategy = MorningSellStrategy(hass, entry_id="entry-1", margin=None)
    strategy.config = {CONF_DISCHARGE_CURRENT_ENTITY: "number.discharge_current"}
    strategy.battery_config = SimpleNamespace(voltage=640.0)
    strategy._use_discharge_current = True
    strategy._regulator_diagnostics = {}

    regulator = strategy._resolve_sell_regulator(5.1)

    assert regulator.value == 0.0


def test_morning_sell_export_power_rounds_up_to_hundreds() -> None:
    """Export regulator rounds the final sell energy up to 100 W."""
    state = MagicMock()
    state.state = "1200"
    state.attributes = {}
    hass = MagicMock()
    hass.states.get.return_value = state
    strategy = MorningSellStrategy(hass, entry_id="entry-1", margin=None)
    strategy.config = {CONF_EXPORT_POWER_ENTITY: "number.export_power"}
    strategy._use_discharge_current = False
    strategy._regulator_diagnostics = {}

    regulator = strategy._resolve_sell_regulator(2.301)

    assert regulator.kind == "export_power"
    assert regulator.previous_value == 1200.0
    assert regulator.value == 2301.0


@pytest.mark.asyncio
async def test_morning_sell_skips_without_valid_hourly_pv_forecast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy aggregate forecast cannot select a Morning sell regulator."""
    config = _base_config()
    config.pop(CONF_PV_FORECAST_TODAY)
    hass = _setup_hass(config, _base_states())
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes[-1].action_type == "no_action"
    assert outcomes[-1].reason == (
        "A valid hourly PV forecast is required to select the sell regulator"
    )


@pytest.mark.asyncio
async def test_morning_sell_skip_records_hourly_forecast_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist parser provenance when hourly data blocks a sell decision."""
    hass = _setup_hass(_base_config(), _base_states())
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)
    monkeypatch.setattr(
        f"{MORNING}.get_morning_pv_forecast",
        lambda *_args, **_kwargs: MorningPVForecast(
            total_kwh=1.0,
            hourly_kwh={},
            status="missing_hourly",
            method="daylight_uniform",
            source_entity="sensor.pv_forecast_today",
            aggregate_kwh=2.0,
            raw_hourly_kwh=None,
            difference_kwh=None,
            tolerance_kwh=None,
            daylight_hours=[7, 8],
            sufficiency_available=False,
            source_state="2",
            source_last_updated="2026-08-14T05:00:00+00:00",
            source_last_changed="2026-08-14T04:00:00+00:00",
            evaluation_time="2026-08-14T07:00:00+02:00",
            evaluation_time_utc="2026-08-14T05:00:00+00:00",
            evaluation_timezone="Europe/Warsaw",
            selected_attribute=None,
            hourly_payload_present=False,
            hourly_payload_length=None,
            first_period_start=None,
            last_period_start=None,
            failure_reason="hourly_attribute_missing",
        ),
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    details = outcomes[-1].details
    assert outcomes[-1].action_type == "no_action"
    assert details["source_entity"] == "sensor.pv_forecast_today"
    assert details["source_state"] == "2"
    assert details["source_last_updated"] == "2026-08-14T05:00:00+00:00"
    assert details["evaluation_time"] == "2026-08-14T07:00:00+02:00"
    assert details["evaluation_time_utc"] == "2026-08-14T05:00:00+00:00"
    assert details["evaluation_timezone"] == "Europe/Warsaw"
    assert details["selected_attribute"] is None
    assert details["hourly_payload_present"] is False
    assert details["hourly_payload_length"] is None
    assert details["first_period_start"] is None
    assert details["last_period_start"] is None
    assert details["failure_reason"] == "hourly_attribute_missing"
    assert details["final_status"] == "missing_hourly"
    assert details["final_method"] == "daylight_uniform"


@pytest.mark.asyncio
async def test_morning_sell_skips_when_forecast_omits_sell_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial hourly forecast cannot select a Morning sell regulator."""
    hass = _setup_hass(_base_config(), _base_states())
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)
    resolve_count = 0

    def _resolve_sell_hour(_strategy: MorningSellStrategy) -> int:
        nonlocal resolve_count
        resolve_count += 1
        return 7

    monkeypatch.setattr(
        MorningSellStrategy,
        "_resolve_sell_hour",
        _resolve_sell_hour,
    )
    monkeypatch.setattr(
        f"{MORNING}.get_morning_pv_forecast",
        lambda *_args, **_kwargs: MorningPVForecast(
            total_kwh=2.0,
            hourly_kwh={hour: 0.0 for hour in range(24) if hour != 7},
            status="valid_hourly",
            method="hourly",
            source_entity="sensor.pv_forecast_today",
            aggregate_kwh=2.0,
            raw_hourly_kwh=2.0,
            difference_kwh=0.0,
            tolerance_kwh=0.25,
            daylight_hours=[],
            sufficiency_available=True,
        ),
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes[-1].action_type == "no_action"
    assert outcomes[-1].reason == (
        "A valid hourly PV forecast is required to select the sell regulator"
    )
    assert resolve_count == 2


@pytest.mark.asyncio
async def test_morning_sell_skips_without_discharge_current_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Current control is not applied when its baseline cannot be restored."""
    config = _base_config()
    config.pop(CONF_DISCHARGE_CURRENT_ENTITY)
    hass = _setup_hass(config, _base_states())
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)
    monkeypatch.setattr(
        f"{MORNING}.get_morning_pv_forecast",
        lambda *_args, **_kwargs: MorningPVForecast(
            total_kwh=10.0,
            hourly_kwh={hour: 10.0 for hour in range(24)},
            status="valid_hourly",
            method="hourly",
            source_entity="sensor.pv_forecast_today",
            aggregate_kwh=10.0,
            raw_hourly_kwh=10.0,
            difference_kwh=0.0,
            tolerance_kwh=1.0,
            daylight_hours=[],
            sufficiency_available=True,
        ),
    )

    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes[-1].action_type == "no_action"
    assert outcomes[-1].reason == (
        "PV covers demand, but no discharge-current entity is configured"
    )


@pytest.mark.asyncio
async def test_morning_sell_skips_when_pv_floor_required_reserve_exceeds_current_soc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    states["sensor.battery_soc"] = "50"
    hass = _setup_hass(config, states)
    outcomes: list = []

    set_work_mode = AsyncMock()
    set_program_soc = AsyncMock()
    set_export_power = AsyncMock()

    async def _capture_log(hass, entry, outcome, context, logger):
        outcomes.append(outcome)

    class _FakeStore:
        def __init__(self, *args, **kwargs):
            pass

        async def async_load(self):
            return None

        async def async_save(self, data):
            return None

    monkeypatch.setattr(f"{SELL_BASE}.log_decision_unified", _capture_log)
    monkeypatch.setattr(f"{SELL_BASE}.Store", _FakeStore)
    monkeypatch.setattr(f"{SELL_BASE}.set_work_mode", set_work_mode)
    monkeypatch.setattr(f"{SELL_BASE}.set_program_soc", set_program_soc)
    monkeypatch.setattr(f"{SELL_BASE}.set_export_power", set_export_power)
    monkeypatch.setattr(
        f"{MORNING}.get_morning_pv_forecast",
        lambda *_args, **_kwargs: MorningPVForecast(
            total_kwh=2.0,
            hourly_kwh={hour: 0.0 for hour in range(24)},
            status="valid_hourly",
            method="hourly",
            source_entity="sensor.pv_forecast_today",
            aggregate_kwh=2.0,
            raw_hourly_kwh=2.0,
            difference_kwh=0.0,
            tolerance_kwh=0.25,
            daylight_hours=[],
            sufficiency_available=True,
        ),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.dt_util.utcnow",
        lambda: datetime(2026, 2, 24, 7, 0, 0),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.dt_util.as_local",
        lambda _dt: SimpleNamespace(hour=7),
    )
    monkeypatch.setattr(
        f"{MORNING}.build_hourly_usage_array",
        lambda config, get_state, daily_load_fallback=None: [0.0] * 24,
    )
    monkeypatch.setattr(
        f"{MORNING}.resolve_tariff_end_hour",
        lambda hass, config, default_hour=13: 13,
    )

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(f"{MORNING}.get_heat_pump_forecast_window", _hp)
    monkeypatch.setattr(
        f"{MORNING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_sufficiency_window",
        lambda **kwargs: (3.0, 2.0, 1.0, 13, True),
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    monkeypatch.setattr(
        f"{MORNING}.calculate_surplus_energy",
        lambda reserve, required, pv: 8.0,
    )
    await async_run_morning_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"
    set_program_soc.assert_awaited()
