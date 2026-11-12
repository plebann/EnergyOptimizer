"""Tests for evening sell decision engine logic."""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_BUY_PRICE_SENSOR,
    CONF_EXPORT_POWER_ENTITY,
    CONF_MAX_EXPORT_POWER,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_MIN_SOC,
    CONF_PROG5_SOC_ENTITY,
    CONF_PV_PRODUCTION_SENSOR,
    CONF_TEST_MODE,
    CONF_WORK_MODE_ENTITY,
    DOMAIN,
    CONF_MAX_DISCHARGE_POWER,
)
from custom_components.energy_optimizer.decision_engine.evening_sell import (
    EveningSellStrategy,
    async_run_evening_sell,
)
from custom_components.energy_optimizer.decision_engine.sell_base import SellRequest
from custom_components.energy_optimizer.calculations.price_windows import ArbitrageBuyHourResult
from custom_components.energy_optimizer.market_windows import (
    MarketWindows,
    MarketWindowSource,
    RankedMarketWindow,
    ResolvedMarketWindow,
    StaticMarketWindowResolver,
    default_market_windows,
)
from custom_components.energy_optimizer.utils.logging import DecisionOutcome

pytestmark = pytest.mark.enable_socket

SELL_BASE = "custom_components.energy_optimizer.decision_engine.sell_base"
EVENING = "custom_components.energy_optimizer.decision_engine.evening_sell"


def _state(value: str) -> MagicMock:
    state = MagicMock()
    if isinstance(value, tuple):
        state.state, state.attributes = value
    else:
        state.state = value
        state.attributes = {}
    return state


_NOW = datetime(2026, 2, 24, 17, tzinfo=ZoneInfo("Europe/Warsaw"))


def _hour_window(
    day_offset: int, hour: int, price: float | None
) -> ResolvedMarketWindow:
    """Build a one-hour price-resolved window on the day of _NOW."""
    start = datetime.combine(
        _NOW.date() + timedelta(days=day_offset), time(hour), tzinfo=_NOW.tzinfo
    )
    return ResolvedMarketWindow(
        start=start,
        end=start + timedelta(hours=1),
        price=price,
        source=MarketWindowSource.PRICES,
    )


def _default_night_buy() -> ResolvedMarketWindow:
    return default_market_windows(_NOW).night_buy


def _windows(
    *,
    primary_hour: int = 17,
    primary_price: float = 700.0,
    secondary_hour: int | None = None,
    secondary_price: float | None = None,
    tomorrow_morning_price: float | None = None,
    night_buy: ResolvedMarketWindow | None = None,
    night_buy_start_hour: int = 1,
) -> MarketWindows:
    """Build the Market Window snapshot an Evening Sell run reads."""
    if night_buy is None:
        start = datetime.combine(
            _NOW.date() + timedelta(days=1),
            time(night_buy_start_hour),
            tzinfo=_NOW.tzinfo,
        )
        night_buy = ResolvedMarketWindow(
            start=start,
            end=start + timedelta(hours=5),
            price=200.0,
            source=MarketWindowSource.PLAN,
        )
    secondary = (
        _hour_window(0, secondary_hour, secondary_price)
        if secondary_hour is not None
        else None
    )
    overrides: dict[str, object] = {
        "evening_sell": RankedMarketWindow(
            primary=_hour_window(0, primary_hour, primary_price),
            secondary=secondary,
        ),
        "night_buy": night_buy,
    }
    if tomorrow_morning_price is not None:
        overrides["morning_sell_tomorrow"] = RankedMarketWindow(
            primary=_hour_window(1, 7, tomorrow_morning_price), secondary=None
        )
    return replace(default_market_windows(_NOW), **overrides)


def _setup_hass(
    config: dict[str, object],
    states: dict[str, str],
    windows: MarketWindows | None = None,
) -> MagicMock:
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
                "market_windows": StaticMarketWindowResolver(
                    windows if windows is not None else _windows()
                ),
            }
        }
    }
    return hass


def _base_config() -> dict[str, object]:
    return {
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_PROG5_SOC_ENTITY: "number.prog5_soc",
        CONF_MIN_ARBITRAGE_PRICE: 400.0,
        CONF_MAX_EXPORT_POWER: 12000,
        CONF_WORK_MODE_ENTITY: "select.work_mode",
        CONF_EXPORT_POWER_ENTITY: "number.export_power",
        CONF_PV_PRODUCTION_SENSOR: "sensor.pv_today",
        CONF_BATTERY_CAPACITY_AH: 37,
        CONF_BATTERY_VOLTAGE: 640,
        CONF_BATTERY_EFFICIENCY: 0.9,
        CONF_TEST_MODE: False,
    }


def _base_states() -> dict[str, str]:
    return {
        "sensor.battery_soc": "90",
        "number.prog5_soc": "50",
        "sensor.pv_today": "8",
    }


def _patch_common(monkeypatch: pytest.MonkeyPatch, outcomes: list) -> None:
    async def _capture_log(hass, entry, outcome, context, logger):
        outcomes.append(outcome)

    monkeypatch.setattr(
        f"{SELL_BASE}.log_decision_unified",
        _capture_log,
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
    class _StoreStub:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def async_save(self, _data: dict[str, object]) -> None:
            return None

        async def async_load(self) -> dict[str, object] | None:
            return None

    monkeypatch.setattr(
        f"{SELL_BASE}.Store",
        _StoreStub,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.dt_util.utcnow",
        lambda: datetime(2026, 2, 24, 16, 0, 0),
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.dt_util.as_local",
        lambda _dt: SimpleNamespace(hour=17),
    )
    monkeypatch.setattr(
        f"{EVENING}.build_hourly_usage_array",
        lambda config, get_state, daily_load_fallback=None: [0.0] * 24,
    )


class _CountingStoreStub:
    save_calls: list[dict[str, object]] = []
    load_data: dict[str, object] | None = None

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def async_save(self, data: dict[str, object]) -> None:
        self.__class__.save_calls.append(dict(data))

    async def async_load(self) -> dict[str, object] | None:
        return self.__class__.load_data


def _sell_request(surplus_kwh: float) -> SellRequest:
    return SellRequest(
        surplus_kwh=surplus_kwh,
        required_kwh=0.0,
        build_outcome_fn=lambda target, surplus, export: DecisionOutcome(
            scenario="Evening Peak Sell",
            action_type="sell",
            summary=f"Sell {surplus:.1f} kWh",
            details={"target_soc": target, "surplus_kwh": surplus, "export_power_w": export},
        ),
        build_no_action_fn=lambda surplus: DecisionOutcome(
            scenario="Evening Peak Sell",
            action_type="no_action",
            summary="No evening peak sell action",
            reason="No sellable surplus remaining",
            details={"surplus_kwh": surplus},
        ),
    )


@pytest.mark.asyncio
async def test_evening_sell_high_sell_action_type(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{EVENING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 10.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_surplus_energy",
        lambda reserve, required, pv: 5.0,
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "high_sell"
    assert outcomes[-1].details["buy_reference_source"] == "plan"


@pytest.mark.asyncio
async def test_evening_sell_uses_next_day_qualifying_buy_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_BUY_PRICE_SENSOR] = "sensor.buy_price"
    states = _base_states()
    hass = _setup_hass(config, states, windows=_windows(night_buy_start_hour=4))
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    local_now = datetime(2026, 2, 24, 17, tzinfo=timezone.utc)
    monkeypatch.setattr(f"{EVENING}.dt_util.as_local", lambda _dt: local_now)
    monkeypatch.setattr(f"{EVENING}.get_buy_price_payload", lambda *args, **kwargs: [{}])
    bounds: dict[str, object] = {}

    def _find(_prices, _entity_id, **kwargs):
        bounds["start"] = kwargs["start_local"]
        bounds["end"] = kwargs["end_local"]
        bounds["max_buy_price"] = kwargs["max_buy_price"]
        return ArbitrageBuyHourResult(
            datetime(2026, 2, 25, 1, tzinfo=timezone.utc),
            200.0,
            500.0,
            "enabled",
        )

    monkeypatch.setattr(f"{EVENING}.find_first_arbitrage_buy_hour", _find)
    forecast_windows: list[tuple[int, int]] = []

    async def _hp(_hass, _config, *, start_hour, end_hour):
        forecast_windows.append((start_hour, end_hour))
        return 1.0, {}

    monkeypatch.setattr(f"{EVENING}.get_heat_pump_forecast_window", _hp)
    monkeypatch.setattr(f"{EVENING}.get_pv_forecast_window", lambda *args, **kwargs: (2.0, {}))
    monkeypatch.setattr(f"{EVENING}.calculate_losses", lambda *args, **kwargs: (0.0, 0.0))
    monkeypatch.setattr(f"{EVENING}.calculate_battery_reserve", lambda *args, **kwargs: 10.0)
    monkeypatch.setattr(f"{EVENING}.calculate_surplus_energy", lambda *args, **kwargs: 5.0)

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert bounds["start"].hour == 18
    assert bounds["end"].date() == datetime(2026, 2, 25).date()
    assert bounds["end"].hour == 4
    assert bounds["max_buy_price"] == 240.0
    assert forecast_windows == [(18, 1), (17, 18)]
    assert outcomes[-1].details["sell_horizon_mode"] == "arbitrage"
    assert outcomes[-1].details["arbitrage_hour"] == 1
    assert outcomes[-1].details["buy_window_reference_price"] == 200.0
    assert outcomes[-1].details["buy_window_reference_source"] == "plan"
    assert outcomes[-1].details["buy_window_price_limit"] == 240.0
    assert outcomes[-1].history_windows == [["sr", 18, "next_h", 1, "arb_b", True]]


@pytest.mark.asyncio
async def test_evening_sell_without_qualifying_buy_price_requires_pv_sufficiency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_BUY_PRICE_SENSOR] = "sensor.buy_price"
    states = _base_states()
    hass = _setup_hass(config, states, windows=_windows(night_buy=_default_night_buy()))
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    local_now = datetime(2026, 2, 24, 17, tzinfo=timezone.utc)
    monkeypatch.setattr(f"{EVENING}.dt_util.as_local", lambda _dt: local_now)
    monkeypatch.setattr(f"{EVENING}.get_buy_price_payload", lambda *args, **kwargs: [{}])
    captured_max_buy_price: float | None = 0.0

    def _find(*args, **kwargs):
        nonlocal captured_max_buy_price
        captured_max_buy_price = kwargs["max_buy_price"]
        return ArbitrageBuyHourResult(None, None, None, "margin_not_reached")

    monkeypatch.setattr(f"{EVENING}.find_first_arbitrage_buy_hour", _find)
    monkeypatch.setattr(f"{EVENING}.get_heat_pump_forecast_window", AsyncMock(return_value=(1.0, {})))
    monkeypatch.setattr(f"{EVENING}.get_pv_forecast_window", lambda *args, **kwargs: (2.0, {}))
    monkeypatch.setattr(f"{EVENING}.calculate_losses", lambda *args, **kwargs: (0.0, 0.0))
    monkeypatch.setattr(f"{EVENING}.calculate_battery_reserve", lambda *args, **kwargs: 10.0)
    monkeypatch.setattr(
        f"{EVENING}.calculate_sufficiency_window",
        lambda **kwargs: (9.0, 8.0, 1.0, 13, False),
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes[-1].action_type == "no_action"
    assert outcomes[-1].details["sell_horizon_mode"] == "normal"
    assert outcomes[-1].details["arbitrage_reason"] == "margin_not_reached"
    assert captured_max_buy_price is None
    assert outcomes[-1].details["buy_window_reference_price"] is None
    assert outcomes[-1].details["buy_window_reference_source"] == "default"
    assert outcomes[-1].details["buy_window_price_limit"] is None


@pytest.mark.asyncio
async def test_evening_sell_high_sell_no_surplus_no_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states)
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{EVENING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 2.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_surplus_energy",
        lambda reserve, required, pv: 0.0,
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert "No surplus energy available" in (outcomes[-1].reason or "")


@pytest.mark.asyncio
async def test_evening_sell_falls_back_to_surplus_sell_when_buy_reference_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states, windows=_windows(night_buy=_default_night_buy()))
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(f"{EVENING}.get_heat_pump_forecast_window", _hp)
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 12.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_sufficiency_window",
        lambda **kwargs: (9.0, 8.0, 1.0, 13, False),
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"
    assert outcomes[-1].details["arbitrage_reason"] == "missing_buy_reference_price"
    assert outcomes[-1].details["buy_reference_source"] == "default"


@pytest.mark.asyncio
async def test_evening_sell_surplus_sell_no_sufficiency_uses_full_tariff_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states, windows=_windows(primary_price=350.0))
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{EVENING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        lambda *args, **kwargs: (2.0, {}),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 12.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_sufficiency_window",
        lambda **kwargs: (9.0, 8.0, 1.0, 13, False),
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"


@pytest.mark.asyncio
async def test_evening_sell_skips_when_tomorrow_morning_price_is_higher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_BUY_PRICE_SENSOR] = "sensor.buy_price"
    states = _base_states()
    hass = _setup_hass(config, states, windows=_windows(primary_price=700.0, tomorrow_morning_price=750.0))
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    set_work_mode_mock = AsyncMock()
    set_program_soc_mock = AsyncMock()
    set_export_power_mock = AsyncMock()
    monkeypatch.setattr(
        f"{SELL_BASE}.set_work_mode",
        set_work_mode_mock,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.set_program_soc",
        set_program_soc_mock,
    )
    monkeypatch.setattr(
        f"{SELL_BASE}.set_export_power",
        set_export_power_mock,
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert "not higher than tomorrow morning" in (outcomes[-1].reason or "").lower()
    assert outcomes[-1].details["window_source"] == "prices"
    set_work_mode_mock.assert_not_awaited()
    set_program_soc_mock.assert_not_awaited()
    set_export_power_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_evening_sell_surplus_sell_success(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states, windows=_windows(primary_price=350.0))
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(hass, config, start_hour, end_hour):
        if start_hour == 0:
            return 1.0, {}
        return 1.0, {}

    def _pv(hass, config, start_hour, end_hour, **kwargs):
        if start_hour == 0:
            return 3.0, {}
        return 1.0, {}

    monkeypatch.setattr(
        f"{EVENING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        _pv,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 12.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_sufficiency_window",
        lambda **kwargs: (9.0, 8.0, 2.0, 5, True),
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "sell"
    assert outcomes[-1].details["sufficiency_hour"] == 5


@pytest.mark.asyncio
async def test_evening_sell_no_action_when_battery_energy_below_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An evening sell whose floored raw target is below the floor exports nothing."""
    config = _base_config()
    config[CONF_MIN_SOC] = 18
    states = _base_states()
    states["sensor.battery_soc"] = "19"
    hass = _setup_hass(config, states, windows=_windows(primary_price=350.0))
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    set_work_mode = AsyncMock()
    set_program_soc = AsyncMock()
    set_export_power = AsyncMock()
    set_discharge_current = AsyncMock()
    monkeypatch.setattr(f"{SELL_BASE}.set_work_mode", set_work_mode)
    monkeypatch.setattr(f"{SELL_BASE}.set_program_soc", set_program_soc)
    monkeypatch.setattr(f"{SELL_BASE}.set_export_power", set_export_power)
    monkeypatch.setattr(f"{SELL_BASE}.set_discharge_current", set_discharge_current)

    async def _hp(*args, **kwargs):
        return 0.0, {}

    monkeypatch.setattr(f"{EVENING}.get_heat_pump_forecast_window", _hp)
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        lambda *args, **kwargs: (0.0, {}),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    # 2.0 kWh sellable surplus above the 19% SOC needs 2.222 kWh from the
    # battery, which floors the raw target to 9.0, below the 18.0 floor.
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 2.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_sufficiency_window",
        lambda **kwargs: (1.0, 0.5, 0.5, 5, True),
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert outcomes[-1].reason == "insufficient battery energy above minimum SOC"
    assert outcomes[-1].details["safety_soc_floor"] == 18.0
    assert outcomes[-1].details["floored_raw_target_soc"] == 9.0
    assert outcomes[-1].details["required_battery_energy_dc_kwh"] == pytest.approx(2.222)
    # Infeasible sell: no inverter write of any regulator kind, no restore payload.
    assert set_work_mode.await_count == 0
    assert set_program_soc.await_count == 0
    assert set_export_power.await_count == 0
    assert set_discharge_current.await_count == 0
    assert "sell_restore" not in hass.data[DOMAIN]["entry-1"]


@pytest.mark.asyncio
async def test_evening_sell_surplus_sell_no_surplus(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states, windows=_windows(primary_price=350.0))
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{EVENING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        lambda *args, **kwargs: (1.0, {}),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 5.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_sufficiency_window",
        lambda **kwargs: (9.0, 8.0, 2.0, 8, True),
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert "No surplus energy" in (outcomes[-1].reason or "")


@pytest.mark.asyncio
async def test_evening_sell_surplus_no_action_required_uses_sufficiency_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    states = _base_states()
    hass = _setup_hass(config, states, windows=_windows(primary_price=350.0))
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 1.0, {}

    monkeypatch.setattr(
        f"{EVENING}.get_heat_pump_forecast_window",
        _hp,
    )
    monkeypatch.setattr(
        f"{EVENING}.get_pv_forecast_window",
        lambda *args, **kwargs: (0.0, {}),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_losses",
        lambda *args, **kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_battery_reserve",
        lambda *args, **kwargs: 5.0,
    )
    monkeypatch.setattr(
        f"{EVENING}.calculate_sufficiency_window",
        lambda **kwargs: (9.0, 8.0, 2.0, 8, True),
    )

    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"
    assert outcomes[-1].details["required_kwh"] == 9.0


@pytest.mark.asyncio
async def test_evening_sell_max_discharge_power_clamp(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DC power limit caps sellable AC at max(0, P_dc * eta * duration - window_demand)."""
    # eta = 0.9, duration = 1.0h, window demand forced to 0 (heat pump forecast 0).
    config = _base_config()
    hass = _setup_hass(config, _base_states())
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 0.0, {}

    monkeypatch.setattr(f"{EVENING}.get_heat_pump_forecast_window", _hp)
    monkeypatch.setattr(f"{EVENING}.get_pv_forecast_window", lambda *args, **kwargs: (2.0, {}))
    monkeypatch.setattr(f"{EVENING}.calculate_losses", lambda *args, **kwargs: (0.0, 0.0))
    monkeypatch.setattr(f"{EVENING}.calculate_battery_reserve", lambda *args, **kwargs: 10.0)
    monkeypatch.setattr(f"{EVENING}.calculate_surplus_energy", lambda reserve, required, pv: 7.0)

    # P_dc = 3.0 kW => max_sell = 3.0 * 0.9 * 1.0 - 0 = 2.7 kWh (surplus 7.0 clamped)
    config[CONF_MAX_DISCHARGE_POWER] = 3.0
    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)
    assert outcomes
    assert outcomes[-1].details["executable_export_ac_kwh"] == pytest.approx(2.7)

    # P_dc = 10.0 kW => max_sell = 9.0 kWh; surplus 7.0 is below the cap
    config[CONF_MAX_DISCHARGE_POWER] = 10.0
    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)
    assert outcomes[-1].details["executable_export_ac_kwh"] == pytest.approx(7.0)

    # No key => no DC cap
    del config[CONF_MAX_DISCHARGE_POWER]
    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)
    assert outcomes[-1].details["executable_export_ac_kwh"] == pytest.approx(7.0)

    # P_dc = 0 => no cap (0 means off)
    config[CONF_MAX_DISCHARGE_POWER] = 0.0
    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)
    assert outcomes[-1].details["executable_export_ac_kwh"] == pytest.approx(7.0)


@pytest.mark.asyncio
async def test_evening_sell_dc_limit_insufficient_no_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Window AC demand at or above the DC energy cap yields no_action."""
    # eta = 0.9, duration = 1.0h. P_dc = 1.0 kW => DC energy = 0.9 kWh.
    # Heat pump window demand = 2.0 kWh (>= 0.9) => no sellable energy.
    config = _base_config()
    hass = _setup_hass(config, _base_states())
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _hp(*args, **kwargs):
        return 2.0, {}

    monkeypatch.setattr(f"{EVENING}.get_heat_pump_forecast_window", _hp)
    monkeypatch.setattr(f"{EVENING}.get_pv_forecast_window", lambda *args, **kwargs: (2.0, {}))
    monkeypatch.setattr(f"{EVENING}.calculate_losses", lambda *args, **kwargs: (0.0, 0.0))
    monkeypatch.setattr(f"{EVENING}.calculate_battery_reserve", lambda *args, **kwargs: 10.0)
    monkeypatch.setattr(f"{EVENING}.calculate_surplus_energy", lambda reserve, required, pv: 7.0)

    config[CONF_MAX_DISCHARGE_POWER] = 1.0
    await async_run_evening_sell(hass, entry_id="entry-1", margin=1.0)

    assert outcomes
    assert outcomes[-1].action_type == "no_action"


@pytest.mark.asyncio
async def test_evening_sell_a_first_splits_primary_then_secondary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_MAX_EXPORT_POWER] = 9000
    states = _base_states()
    states["sensor.pv_today"] = "20"
    hass = _setup_hass(config, states, windows=_windows(primary_hour=18, secondary_hour=19, secondary_price=600.0, tomorrow_morning_price=500.0))
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _compute_base(self):
        return _sell_request(12.0 if self._is_primary else 3.0)

    monkeypatch.setattr(f"{EVENING}.EveningSellStrategy._compute_base_evaluation", _compute_base)
    _CountingStoreStub.save_calls = []
    _CountingStoreStub.load_data = None
    monkeypatch.setattr(f"{SELL_BASE}.Store", _CountingStoreStub)

    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=True,
        is_first=True,
    )
    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=False,
        is_first=False,
    )

    assert [outcome.details["surplus_kwh"] for outcome in outcomes[-2:]] == [9.0, 3.0]
    assert len(_CountingStoreStub.save_calls) == 1


@pytest.mark.asyncio
async def test_evening_sell_b_first_sells_only_overflow_before_primary_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_MAX_EXPORT_POWER] = 9000
    states = _base_states()
    states["sensor.pv_today"] = "20"
    hass = _setup_hass(config, states, windows=_windows(primary_hour=19, secondary_hour=18, secondary_price=600.0, tomorrow_morning_price=500.0))
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _compute_base(self):
        if not self._is_primary and self._is_first:
            return _sell_request(12.0)
        return _sell_request(9.0)

    monkeypatch.setattr(f"{EVENING}.EveningSellStrategy._compute_base_evaluation", _compute_base)
    _CountingStoreStub.save_calls = []
    _CountingStoreStub.load_data = None
    monkeypatch.setattr(f"{SELL_BASE}.Store", _CountingStoreStub)

    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=False,
        is_first=True,
    )
    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=True,
        is_first=False,
    )

    assert [outcome.details["surplus_kwh"] for outcome in outcomes[-2:]] == [3.0, 9.0]
    assert len(_CountingStoreStub.save_calls) == 1


@pytest.mark.asyncio
async def test_evening_sell_second_window_early_exit_restores_active_sell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_MAX_EXPORT_POWER] = 9000
    config[CONF_BUY_PRICE_SENSOR] = "sensor.buy_price"
    states = _base_states()
    hass = _setup_hass(config, states, windows=_windows(primary_hour=18, secondary_hour=19, secondary_price=400.0, tomorrow_morning_price=500.0))
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _compute_base(self):
        return _sell_request(8.0)

    monkeypatch.setattr(f"{EVENING}.EveningSellStrategy._compute_base_evaluation", _compute_base)

    restore_mock = AsyncMock()
    monkeypatch.setattr(f"{EVENING}.async_handle_sell_restore", restore_mock)

    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=True,
        is_first=True,
    )
    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=False,
        is_first=False,
    )

    assert restore_mock.await_count == 1
    assert outcomes[-1].action_type == "sell_restore"
    assert outcomes[-1].details["window_source"] == "prices"


@pytest.mark.asyncio
async def test_evening_sell_second_window_zero_surplus_restores_active_sell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config()
    config[CONF_MAX_EXPORT_POWER] = 9000
    states = _base_states()
    hass = _setup_hass(config, states, windows=_windows(primary_hour=18, secondary_hour=19, secondary_price=600.0, tomorrow_morning_price=500.0))
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)

    async def _compute_base(self):
        if self._is_primary:
            return _sell_request(8.0)
        return DecisionOutcome(
            scenario="Evening Peak Sell",
            action_type="no_action",
            summary="No evening peak sell action",
            reason="No surplus energy available for selling",
            details={},
        )

    monkeypatch.setattr(f"{EVENING}.EveningSellStrategy._compute_base_evaluation", _compute_base)

    restore_mock = AsyncMock()
    monkeypatch.setattr(f"{EVENING}.async_handle_sell_restore", restore_mock)

    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=True,
        is_first=True,
    )
    await async_run_evening_sell(
        hass,
        entry_id="entry-1",
        margin=1.0,
        is_primary=False,
        is_first=False,
    )

    assert restore_mock.await_count == 1
    assert outcomes[-1].action_type == "sell_restore"
    assert outcomes[-1].details["window_source"] == "prices"


@pytest.mark.asyncio
async def test_evening_sell_reads_one_snapshot_per_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run asks the resolver once, however many windows it reads."""
    hass = _setup_hass(_base_config(), _base_states())
    outcomes: list = []
    _patch_common(monkeypatch, outcomes)
    resolver = MagicMock(wraps=StaticMarketWindowResolver(_windows()))

    async def _compute_base(self):
        return _sell_request(2.0)

    monkeypatch.setattr(f"{EVENING}.EveningSellStrategy._compute_base_evaluation", _compute_base)
    strategy = EveningSellStrategy(
        hass, entry_id="entry-1", margin=1.0, resolver=resolver
    )

    await strategy.run()

    assert resolver.windows.call_count == 1
    assert strategy.windows == _windows()
