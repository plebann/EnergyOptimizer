"""Public-seam tests for afternoon charge planning."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_GRID_CHARGE_CURRENT_ENTITY,
    CONF_EVENING_MAX_PRICE_SENSOR,
    CONF_MAX_SOC,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_MIN_SOC,
    CONF_PROG4_SOC_ENTITY,
    CONF_PROG4_TIME_START_ENTITY,
    CONF_TEST_MODE,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.afternoon_charge import (
    async_run_afternoon_charge,
)
from custom_components.energy_optimizer.decision_engine.common import ForecastData
from custom_components.energy_optimizer.market_windows import (
    MarketWindowSource,
    RankedMarketWindow,
    ResolvedHour,
    StaticMarketWindowResolver,
)
from tests.conftest import market_windows, window

pytestmark = pytest.mark.enable_socket

_AFTERNOON_MODULE = (
    "custom_components.energy_optimizer.decision_engine.afternoon_charge"
)
_CHARGE_BASE_MODULE = (
    "custom_components.energy_optimizer.decision_engine.charge_base"
)


def _forecast(
    *,
    usage: dict[int, float] | None = None,
    pv: dict[int, float] | None = None,
    start_hour: int = 12,
    end_hour: int = 4,
) -> ForecastData:
    """Build an hourly forecast for the afternoon horizon."""
    usage = usage or {}
    pv = pv or {}
    hours = (
        list(range(start_hour, 24)) + list(range(end_hour))
        if end_hour < start_hour
        else list(range(start_hour, end_hour))
    )
    hourly_usage = [usage.get(hour, 0.0) for hour in range(24)]
    return ForecastData(
        start_hour=start_hour,
        end_hour=end_hour,
        hours=len(hours),
        hourly_usage=hourly_usage,
        usage_kwh=sum(hourly_usage[hour] for hour in hours),
        heat_pump_kwh=0.0,
        heat_pump_hourly={},
        pv_forecast_kwh=sum(pv.get(hour, 0.0) for hour in hours),
        pv_forecast_hourly=pv,
        losses_hourly=0.0,
        losses_kwh=0.0,
        margin=1.0,
    )


def _hass(
    *,
    current_soc: float,
    max_soc: float = 100.0,
    efficiency: float = 100.0,
    capacity_ah: float = 100.0,
    voltage: float = 50.0,
) -> tuple[MagicMock, MagicMock]:
    """Build a minimal Home Assistant harness with observable outputs."""
    config = {
        CONF_PROG4_SOC_ENTITY: "number.program4_soc",
        CONF_PROG4_TIME_START_ENTITY: "time.program4_start",
        CONF_GRID_CHARGE_CURRENT_ENTITY: "number.charge_current",
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_BATTERY_CAPACITY_AH: capacity_ah,
        CONF_BATTERY_VOLTAGE: voltage,
        CONF_MIN_SOC: 20.0,
        CONF_MAX_SOC: max_soc,
        CONF_BATTERY_EFFICIENCY: efficiency,
        CONF_EVENING_MAX_PRICE_SENSOR: "sensor.evening_price",
        CONF_MIN_ARBITRAGE_PRICE: 0.2,
        CONF_TEST_MODE: False,
    }
    states = {
        "number.program4_soc": str(current_soc),
        "time.program4_start": "11:00:00",
        "number.charge_current": "0",
        "sensor.battery_soc": str(current_soc),
        "sensor.evening_price": "1.0",
    }
    entry = MagicMock(entry_id="entry-1", domain=DOMAIN, data=config)
    hass = MagicMock()
    hass.config_entries.async_get_entry.return_value = entry
    hass.config_entries.async_entries.return_value = [entry]

    def _get_state(entity_id: str) -> MagicMock | None:
        if entity_id not in states:
            return None
        state = MagicMock()
        state.state = states[entity_id]
        state.attributes = {}
        return state

    hass.states.get.side_effect = _get_state
    hass.services.async_call = AsyncMock()
    hass.services.has_service.return_value = False
    hass.bus.async_fire = MagicMock()

    optimization = MagicMock()
    history = MagicMock()
    assist = MagicMock()
    hass.data = {
        DOMAIN: {
            "entry-1": {
                "last_optimization_sensor": optimization,
                "optimization_history_sensor": history,
                "market_windows": StaticMarketWindowResolver(market_windows()),
                "afternoon_grid_assist_sensor": assist,
            }
        }
    }
    return hass, assist


async def _run(
    hass: MagicMock,
    forecast: ForecastData,
    *,
    arbitrage_enabled: bool,
    tomorrow_start_hour: int | None = 4,
    day_buy_end_hour: int = 14,
) -> dict[str, object]:
    """Run the public afternoon entry point with deterministic windows."""
    gate = (
        True,
        {
            "sell_price": 1.0,
            "buy_reference_price": 0.3,
            "arbitrage_margin": 0.7,
            "min_arbitrage_price": 0.2,
            "arbitrage_reason": "enabled",
        },
    )
    if not arbitrage_enabled:
        gate = (
            False,
            {
                "sell_price": 0.4,
                "buy_reference_price": 0.3,
                "arbitrage_margin": 0.1,
                "min_arbitrage_price": 0.2,
                "arbitrage_reason": "margin_below_threshold",
            },
        )

    hass.data[DOMAIN]["entry-1"]["market_windows"] = StaticMarketWindowResolver(
        market_windows(
            day_buy=window(12, day_buy_end_hour, 0.3),
            night_buy=(
                market_windows().night_buy
                if tomorrow_start_hour is None
                else window(tomorrow_start_hour, 6, 0.3, next_day=True)
            ),
            night_buy_after=window(1, 5, 0.3, next_day=True),
            evening_sell=RankedMarketWindow(primary=window(18, 19, 1.0), secondary=None),
            high_tariff_start=ResolvedHour(14, MarketWindowSource.PRICES),
        )
    )

    with ExitStack() as stack:
        gather_mock = stack.enter_context(
            patch(
                f"{_CHARGE_BASE_MODULE}.gather_forecasts",
                AsyncMock(return_value=forecast),
            )
        )
        stack.enter_context(
            patch(
                f"{_AFTERNOON_MODULE}.resolve_arbitrage_margin_gate",
                return_value=gate,
            )
        )
        stack.enter_context(
            patch(
                f"{_AFTERNOON_MODULE}.async_schedule_charge_completion",
                AsyncMock(),
            )
        )
        await async_run_afternoon_charge(hass, entry_id="entry-1", margin=1.0)

    assert gather_mock.call_args.kwargs["start_hour"] == 12
    assert gather_mock.call_args.kwargs["end_hour"] == (
        22 if tomorrow_start_hour is None else tomorrow_start_hour
    )
    optimization = hass.data[DOMAIN]["entry-1"]["last_optimization_sensor"]
    optimization.log_optimization.assert_called_once()
    return optimization.log_optimization.call_args.args[1]


@pytest.mark.asyncio
async def test_protection_charge_sets_program_current_and_grid_assist() -> None:
    """Protection includes the full buy window and turns on grid assist."""
    hass, assist = _hass(current_soc=20.0)
    details = await _run(
        hass,
        _forecast(usage={12: 0.5, 13: 0.5, 14: 0.5}),
        arbitrage_enabled=False,
    )

    assert details["protection_grid_charge_kwh"] == pytest.approx(1.5, abs=0.01)
    assert details["planned_grid_charge_kwh"] == pytest.approx(1.5, abs=0.01)
    assert details["projected_load_grid_import_kwh"] == pytest.approx(0.0, abs=0.01)
    assist.set_assist.assert_called_once_with(True)

    number_calls = [
        call.args[2]
        for call in hass.services.async_call.call_args_list
        if call.args[:2] == ("number", "set_value")
    ]
    assert any(call["entity_id"] == "number.program4_soc" for call in number_calls)
    assert any(
        call["entity_id"] == "number.charge_current" and call["value"] > 0
        for call in number_calls
    )
    time_calls = [
        call.args[2]
        for call in hass.services.async_call.call_args_list
        if call.args[:2] == ("time", "set_value")
    ]
    assert time_calls == [{"entity_id": "time.program4_start", "time": "12:00:00"}]


@pytest.mark.asyncio
async def test_protection_restores_an_initial_soc_below_the_safety_floor() -> None:
    """Measured SOC below min_soc requires grid energy to restore the floor."""
    hass, assist = _hass(current_soc=10.0)
    details = await _run(
        hass,
        _forecast(),
        arbitrage_enabled=False,
    )

    assert details["protection_grid_charge_kwh"] == pytest.approx(0.5, abs=0.01)
    assert details["projected_end_soc"] == pytest.approx(20.0, abs=0.01)
    assist.set_assist.assert_called_once_with(True)


@pytest.mark.asyncio
async def test_infeasible_floor_restoration_reports_the_remaining_deficit() -> None:
    """An unreachable initial safety floor is included in the protection deficit."""
    hass, _ = _hass(current_soc=0.0)
    entry = hass.config_entries.async_get_entry.return_value
    entry.data[CONF_MIN_SOC] = 80.0
    details = await _run(
        hass,
        _forecast(),
        arbitrage_enabled=True,
    )

    assert details["protection_grid_charge_kwh"] == pytest.approx(3.2, abs=0.01)
    assert details["uncovered_reserve_deficit_kwh"] == pytest.approx(0.8, abs=0.01)
    assert details["arbitrage_reason"] == "protection_infeasible"


@pytest.mark.asyncio
async def test_pv_surplus_exports_and_uses_configured_max_soc_space() -> None:
    """Only physically storable PV fills the configured max-SOC space."""
    hass, assist = _hass(current_soc=70.0, max_soc=80.0)
    details = await _run(
        hass,
        _forecast(usage={12: 0.5}, pv={12: 2.0}),
        arbitrage_enabled=False,
    )

    assert details["forecast_pv_surplus_kwh"] == pytest.approx(1.5)
    assert details["pv_stored_kwh"] == pytest.approx(0.5)
    assert details["forecast_export_kwh"] == pytest.approx(1.0)
    assert details["projected_end_soc"] == pytest.approx(80.0)
    assert details["physical_free_space_end_kwh"] == pytest.approx(0.0)
    assist.set_assist.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_storable_pv_capacity_has_priority_over_arbitrage() -> None:
    """Arbitrage uses only capacity left after forecast PV storage."""
    hass, _ = _hass(current_soc=20.0, capacity_ah=10.0, voltage=500.0)
    details = await _run(
        hass,
        _forecast(pv={15: 3.0}),
        arbitrage_enabled=True,
    )

    assert details["pv_stored_kwh"] == pytest.approx(3.0, abs=0.01)
    assert details["arbitrage_grid_charge_kwh"] == pytest.approx(1.0, abs=0.01)
    assert details["forecast_export_kwh"] == pytest.approx(0.0, abs=0.01)


@pytest.mark.asyncio
async def test_arbitrage_keeps_pv_storage_at_each_forecast_hour() -> None:
    """Arbitrage cannot replace early PV storage with PV after virtual sale."""
    hass, _ = _hass(current_soc=20.0, capacity_ah=10.0, voltage=500.0)
    details = await _run(
        hass,
        _forecast(pv={15: 3.0, 19: 3.0}),
        arbitrage_enabled=True,
    )

    pv_hours = {
        entry["hour"]: entry["pv_stored_kwh"]
        for entry in details["hourly_trace"]
        if entry["hour"] in {15, 19}
    }
    assert pv_hours[15] == pytest.approx(3.0, abs=0.01)
    assert pv_hours[19] == pytest.approx(1.0, abs=0.01)
    assert details["arbitrage_grid_charge_kwh"] == pytest.approx(1.0, abs=0.01)


@pytest.mark.asyncio
async def test_virtual_sale_preserves_protection_above_min_soc() -> None:
    """Arbitrage cannot consume energy needed for post-sale protected loads."""
    hass, _ = _hass(current_soc=20.0, capacity_ah=10.0, voltage=500.0)
    details = await _run(
        hass,
        _forecast(usage={19: 2.0}),
        arbitrage_enabled=True,
    )

    assert details["protection_grid_charge_kwh"] == pytest.approx(2.0, abs=0.01)
    assert details["arbitrage_grid_charge_kwh"] == pytest.approx(2.0, abs=0.01)
    assert details["projected_load_grid_import_kwh"] == pytest.approx(0.0, abs=0.01)
    assert details["projected_end_soc"] == pytest.approx(20.0, abs=0.01)


@pytest.mark.asyncio
async def test_infeasible_protection_disables_arbitrage_and_reports_deficit() -> None:
    """Maximum feasible protection is used without adding arbitrage."""
    hass, assist = _hass(current_soc=20.0)
    details = await _run(
        hass,
        _forecast(usage={19: 5.0}),
        arbitrage_enabled=True,
    )

    assert details["protection_grid_charge_kwh"] == pytest.approx(2.6, abs=0.02)
    assert details["arbitrage_grid_charge_kwh"] == pytest.approx(0.0)
    assert details["uncovered_reserve_deficit_kwh"] == pytest.approx(2.4, abs=0.02)
    assert details["arbitrage_reason"] == "protection_infeasible"
    assist.set_assist.assert_called_once_with(True)


@pytest.mark.asyncio
async def test_tapered_charge_current_satisfies_protection_capacity() -> None:
    """Protection succeeds at the programmed current across the taper boundary."""
    hass, _ = _hass(current_soc=69.0)
    details = await _run(
        hass,
        _forecast(usage={14: 2.925}),
        arbitrage_enabled=True,
        day_buy_end_hour=13,
    )

    assert details["charge_current_a"] == 19.0
    assert details["uncovered_reserve_deficit_kwh"] == pytest.approx(0.0, abs=0.01)
    assert details["arbitrage_reason"] == "enabled"


@pytest.mark.asyncio
async def test_afternoon_metrics_use_new_public_contract() -> None:
    """Published metrics include the redesign contract and omit legacy aliases."""
    hass, _ = _hass(current_soc=20.0, efficiency=80.0)
    details = await _run(
        hass,
        _forecast(usage={14: 0.8}),
        arbitrage_enabled=False,
    )

    assert details["planned_grid_charge_kwh"] == pytest.approx(1.25, abs=0.02)
    assert "free_after_kwh" not in details
    assert "required_kwh" not in details
    assert {
        "forecast_consumption_kwh",
        "forecast_pv_surplus_kwh",
        "planned_grid_charge_kwh",
        "projected_load_grid_import_kwh",
        "projected_end_soc",
        "physical_free_space_end_kwh",
        "protection_grid_charge_kwh",
        "arbitrage_grid_charge_kwh",
        "pv_stored_kwh",
        "grid_charge_stored_kwh",
        "forecast_export_kwh",
        "uncovered_reserve_deficit_kwh",
        "hourly_trace",
    } <= details.keys()

    history = hass.data[DOMAIN]["entry-1"]["optimization_history_sensor"]
    history_details = history.add_entry.call_args.args[1]
    assert "hourly_trace" not in history_details


@pytest.mark.asyncio
async def test_no_grid_charge_targets_peak_plus_safety_margin() -> None:
    """Issue #56: the Program 4 target is the charge-window peak + 1 point.

    No demand, no PV, no arbitrage: the window peak is the current SOC 44.3,
    so the target is ceil(44.3) + 1 = 46 instead of today's ceil(44.3) = 45.
    """
    hass, _ = _hass(current_soc=44.3)
    details = await _run(
        hass,
        _forecast(),
        arbitrage_enabled=False,
    )

    assert details["target_soc"] == pytest.approx(46.0)


@pytest.mark.asyncio
async def test_no_grid_charge_target_capped_at_max_soc() -> None:
    """Issue #56: peak 43.2 rounds up to 44; +1 lands exactly on max_soc 45."""
    hass, _ = _hass(current_soc=43.2, max_soc=45.0)
    details = await _run(
        hass,
        _forecast(),
        arbitrage_enabled=False,
    )

    assert details["target_soc"] == pytest.approx(45.0)


@pytest.mark.asyncio
async def test_forecast_horizon_falls_back_to_night_window_start() -> None:
    """Unavailable tomorrow pricing ends the horizon at the 22:00 night start."""
    hass, _ = _hass(current_soc=50.0)
    details = await _run(
        hass,
        _forecast(start_hour=12, end_hour=22),
        arbitrage_enabled=False,
        tomorrow_start_hour=None,
    )

    assert details["window_start_hour"] == 12
    assert details["window_end_hour"] == 22


@pytest.mark.asyncio
async def test_afternoon_charge_is_skipped_without_a_day_buy_window() -> None:
    """A Default Day Buy Window (no plan for today) forecasts and charges nothing."""
    hass, _assist = _hass(current_soc=50.0)
    entry = hass.config_entries.async_get_entry.return_value
    default_day_buy = market_windows().day_buy
    assert default_day_buy.source is MarketWindowSource.DEFAULT
    hass.data[DOMAIN]["entry-1"]["market_windows"] = StaticMarketWindowResolver(
        market_windows(day_buy=default_day_buy)
    )
    gather_mock = AsyncMock()

    with patch(f"{_CHARGE_BASE_MODULE}.gather_forecasts", gather_mock):
        await async_run_afternoon_charge(hass, entry_id="entry-1", margin=1.0)

    gather_mock.assert_not_called()
    optimization = hass.data[DOMAIN]["entry-1"]["last_optimization_sensor"]
    optimization.log_optimization.assert_called_once()
    assert optimization.log_optimization.call_args.args[1] == {
        "result": "Afternoon charge skipped: no Day Buy Window"
    }


@pytest.mark.asyncio
async def test_completion_is_scheduled_at_the_snapshot_day_buy_window() -> None:
    """Completion runs at (day_buy.start, day_buy.end) of the snapshot."""
    hass, _ = _hass(current_soc=20.0)
    day_buy = window(12, 14, 0.3)
    hass.data[DOMAIN]["entry-1"]["market_windows"] = StaticMarketWindowResolver(
        market_windows(day_buy=day_buy)
    )
    schedule = AsyncMock()

    with (
        patch(
            f"{_CHARGE_BASE_MODULE}.gather_forecasts",
            AsyncMock(return_value=_forecast(usage={14: 0.8})),
        ),
        patch(f"{_AFTERNOON_MODULE}.async_schedule_charge_completion", schedule),
    ):
        await async_run_afternoon_charge(hass, entry_id="entry-1", margin=1.0)

    schedule.assert_awaited_once()
    kwargs = schedule.await_args.kwargs
    assert (kwargs["window_start"], kwargs["window_end"]) == (day_buy.start, day_buy.end)
    assert kwargs["complete_at"] == day_buy.end
    assert kwargs["window_source"] == day_buy.source.value


@pytest.mark.asyncio
async def test_afternoon_charge_runs_with_a_planned_day_buy_window() -> None:
    """A Day Buy Window from the plan for today is not skipped."""
    hass, _ = _hass(current_soc=20.0)
    planned = replace(window(13, 15, 0.3), source=MarketWindowSource.PLAN)
    hass.data[DOMAIN]["entry-1"]["market_windows"] = StaticMarketWindowResolver(
        market_windows(day_buy=planned)
    )
    gather_mock = AsyncMock(return_value=_forecast(usage={14: 0.8}))

    with (
        patch(f"{_CHARGE_BASE_MODULE}.gather_forecasts", gather_mock),
        patch(f"{_AFTERNOON_MODULE}.async_schedule_charge_completion", AsyncMock()),
    ):
        await async_run_afternoon_charge(hass, entry_id="entry-1", margin=1.0)

    gather_mock.assert_called_once()
    assert gather_mock.call_args.kwargs["start_hour"] == 13
