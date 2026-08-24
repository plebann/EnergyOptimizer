"""Tests for morning charge arbitrage logic."""
from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_DAILY_LOAD_SENSOR,
    CONF_EVENING_MAX_PRICE_SENSOR,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_MORNING_MAX_PRICE_SENSOR,
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG2_TIME_START_ENTITY,
    CONF_PV_FORECAST_REMAINING,
    CONF_HIGH_TARIFF_END_HOUR_SENSOR,
    CONF_TEST_MODE,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.common import (
    BatteryConfig,
    ForecastData,
    _compute_arbitrage_from_cap,
    resolve_arbitrage_margin_gate,
)
from custom_components.energy_optimizer.decision_engine.afternoon_charge import (
    AfternoonChargeStrategy,
    _calculate_arbitrage_kwh,
)
from custom_components.energy_optimizer.decision_engine.morning_charge import (
    _calculate_morning_arbitrage_kwh,
    async_run_morning_charge,
)

pytestmark = pytest.mark.enable_socket

_INTERNAL_SENSOR_PATCH = "custom_components.energy_optimizer.helpers.get_internal_sensor_entity_id"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bc(capacity_ah: float = 100.0, voltage: float = 50.0) -> BatteryConfig:
    return BatteryConfig(
        capacity_ah=capacity_ah,
        voltage=voltage,
        min_soc=20.0,
        min_soc_pv=15.0,
        max_soc=100.0,
        efficiency=100.0,
    )


def _forecasts(
    *,
    start_hour: int = 6,
    end_hour: int = 13,
    pv_hourly: dict[int, float] | None = None,
    usage: float = 0.3,
) -> ForecastData:
    hour_window = list(range(start_hour, end_hour))
    hourly_usage = [usage] * 24
    pv_hourly = pv_hourly or {}
    return ForecastData(
        start_hour=start_hour,
        end_hour=end_hour,
        hours=len(hour_window),
        hourly_usage=hourly_usage,
        usage_kwh=sum(hourly_usage[h] for h in hour_window),
        heat_pump_kwh=0.0,
        heat_pump_hourly={},
        pv_forecast_kwh=sum(pv_hourly.values()),
        pv_forecast_hourly=pv_hourly,
        losses_hourly=0.0,
        losses_kwh=0.0,
        margin=1.0,
    )


def _hass_with_states(config: dict, states: dict) -> MagicMock:
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.domain = DOMAIN
    entry.data = config
    hass.config_entries.async_entries.return_value = [entry]
    hass.config_entries.async_get_entry.return_value = entry

    def _get_state(entity_id: str) -> MagicMock | None:
        if entity_id not in states:
            return None
        s = MagicMock()
        v = states[entity_id]
        if isinstance(v, tuple):
            s.state, s.attributes = v
        else:
            s.state = v
            s.attributes = {}
        return s

    hass.states.get.side_effect = _get_state
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    mock_opt = MagicMock()
    mock_opt.log_optimization = MagicMock()
    mock_hist = MagicMock()
    mock_hist.add_entry = MagicMock()
    hass.data = {
        DOMAIN: {
            "entry-1": {
                "last_optimization_sensor": mock_opt,
                "optimization_history_sensor": mock_hist,
            }
        }
    }
    return hass


# ---------------------------------------------------------------------------
# Unit tests: _compute_arbitrage_from_cap
# ---------------------------------------------------------------------------


def test_compute_arbitrage_from_cap_basic():
    """Returns arbitrage_kwh = cap_kwh when free space exceeds cap."""
    bc = _bc(capacity_ah=100, voltage=50)  # 5 kWh full
    # current_soc=50 -> 2.5 kWh stored, required=0.5 -> free_after=2.0; cap=1.0
    forecasts = _forecasts(start_hour=6, end_hour=13)
    kwh, metrics = _compute_arbitrage_from_cap(
        bc=bc,
        forecasts=forecasts,
        sell_start_hour=10,
        current_soc=50.0,
        required_kwh=0.5,
        cap_kwh=1.0,
    )
    assert kwh == pytest.approx(1.0)
    assert metrics["arb_limit_kwh"] == pytest.approx(2.0)
    assert metrics["sell_window_start_hour"] == 10


def test_afternoon_charge_uses_day_buy_window_duration_for_current_sizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Day buy-window duration controls afternoon charge-current sizing."""
    strategy = AfternoonChargeStrategy(MagicMock(), entry_id="entry-1", margin=None)
    strategy.entry = MagicMock(entry_id="entry-1")
    strategy.config = {}
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.afternoon_charge.resolve_day_buy_window_duration_hours",
        lambda *args, **kwargs: 3.0,
    )

    assert strategy._resolve_charge_time_hours() == pytest.approx(3.0)


def test_afternoon_charge_ends_at_midnight_without_tomorrow_night_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Afternoon forecast ends today when tomorrow night prices are unavailable."""
    strategy = AfternoonChargeStrategy(MagicMock(), entry_id="entry-1", margin=None)
    strategy.entry = MagicMock(entry_id="entry-1")
    strategy.config = {}
    captured: dict[str, int | None] = {}

    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.afternoon_charge.resolve_tariff_start_hour",
        lambda *args, **kwargs: 14,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.afternoon_charge.resolve_day_buy_window_end_hour",
        lambda *args, **kwargs: 14,
    )

    def _resolve_tomorrow_night(
        *_args,
        default_hour: int | None,
        **_kwargs,
    ) -> int | None:
        captured["default_hour"] = default_hour
        return default_hour

    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.afternoon_charge.resolve_night_buy_window_tomorrow_start_hour",
        _resolve_tomorrow_night,
    )

    start_hour, end_hour, _ = strategy._resolve_forecast_params()

    assert captured["default_hour"] is None
    assert (start_hour, end_hour) == (14, 24)
    assert strategy._history_window_kinds() == ("db_e", "day_e")


def test_afternoon_charge_uses_available_tomorrow_night_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Afternoon forecast continues to the resolved tomorrow night window."""
    strategy = AfternoonChargeStrategy(MagicMock(), entry_id="entry-1", margin=None)
    strategy.entry = MagicMock(entry_id="entry-1")
    strategy.config = {}

    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.afternoon_charge.resolve_tariff_start_hour",
        lambda *args, **kwargs: 14,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.afternoon_charge.resolve_day_buy_window_end_hour",
        lambda *args, **kwargs: 14,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.afternoon_charge.resolve_night_buy_window_tomorrow_start_hour",
        lambda *args, **kwargs: 4,
    )

    start_hour, end_hour, _ = strategy._resolve_forecast_params()

    assert (start_hour, end_hour) == (14, 4)
    assert strategy._history_window_kinds() == ("db_e", "nb_t_s")


def test_compute_arbitrage_from_cap_limited_by_arb_limit():
    """arbitrage_kwh is capped to arb_limit when cap_kwh > arb_limit."""
    bc = _bc(capacity_ah=100, voltage=50)  # 5 kWh
    # current_soc=90 -> 4.5 kWh, required=0.3 -> free_after=0.2; cap=5.0
    forecasts = _forecasts(start_hour=6, end_hour=13)
    kwh, metrics = _compute_arbitrage_from_cap(
        bc=bc,
        forecasts=forecasts,
        sell_start_hour=10,
        current_soc=90.0,
        required_kwh=0.3,
        cap_kwh=5.0,
    )
    assert kwh == pytest.approx(0.2, abs=0.01)
    assert metrics["arb_limit_kwh"] == pytest.approx(0.2, abs=0.01)


def test_compute_arbitrage_from_cap_surplus_reduces_arb_limit():
    """PV surplus expected before sell window shrinks the arb_limit.

    dt_util.utcnow is patched to 03:00 UTC so now_hour=3 < start_hour=6,
    meaning hours 6-9 (before sell_start_hour=10) are included in the surplus window.
    """
    frozen_utc = dt.datetime(2024, 1, 15, 3, 0, 0, tzinfo=dt.timezone.utc)
    with patch(
        "homeassistant.util.dt.utcnow",
        return_value=frozen_utc,
    ):
        bc = _bc(capacity_ah=100, voltage=50)  # 5 kWh
        # now_hour=3 (UTC), surplus_start=max(6,3)=6, surplus_end=min(10,13)=10
        # pv[6]=1.0, demand[6]=0.3*1.0(margin) -> net_surplus=0.7 -> arb_limit=1.8
        forecasts = _forecasts(
            start_hour=6,
            end_hour=13,
            pv_hourly={6: 1.0},
            usage=0.3,
        )
        kwh, metrics = _compute_arbitrage_from_cap(
            bc=bc,
            forecasts=forecasts,
            sell_start_hour=10,
            current_soc=50.0,
            required_kwh=0.0,
            cap_kwh=5.0,
        )
    assert metrics["surplus_kwh"] == pytest.approx(0.7, abs=0.01)
    assert metrics["arb_limit_kwh"] == pytest.approx(1.8, abs=0.01)
    assert kwh == pytest.approx(1.8, abs=0.01)


def test_compute_arbitrage_from_cap_zero_when_battery_full():
    """Returns 0.0 when battery is at max SOC with no free space."""
    bc = _bc(capacity_ah=100, voltage=50)  # 5 kWh
    # current_soc=100 + required=0 -> free_after=0
    forecasts = _forecasts(start_hour=6, end_hour=13)
    kwh, metrics = _compute_arbitrage_from_cap(
        bc=bc,
        forecasts=forecasts,
        sell_start_hour=10,
        current_soc=100.0,
        required_kwh=0.0,
        cap_kwh=5.0,
    )
    assert kwh == pytest.approx(0.0)
    assert metrics["arb_limit_kwh"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Unit tests: _calculate_morning_arbitrage_kwh
# ---------------------------------------------------------------------------


def _arb_config(
    sell_price_entity: str = "sensor.morning_price",
    remaining_entity: str = "sensor.pv_remaining",
    min_price: float = 0.5,
) -> dict:
    return {
        CONF_MORNING_MAX_PRICE_SENSOR: sell_price_entity,
        CONF_PV_FORECAST_REMAINING: remaining_entity,
        CONF_MIN_ARBITRAGE_PRICE: min_price,
    }


def _afternoon_arb_config(
    sell_price_entity: str = "sensor.evening_price",
    min_price: float = 0.5,
) -> dict:
    return {
        CONF_EVENING_MAX_PRICE_SENSOR: sell_price_entity,
        CONF_MIN_ARBITRAGE_PRICE: min_price,
    }


def _internal_sensor_id(_hass, *, entry_id: str, unique_id_suffix: str, entity_domain: str = "sensor") -> str | None:
    mapping = {
        "night_buy_window": "sensor.night_buy_window_internal",
        "day_buy_window": "sensor.day_buy_window_internal",
    }
    return mapping.get(unique_id_suffix)


def _arb_hass(
    sell_price: str | None = "0.8",
    remaining: str | None = "3.0",
    *,
    night_buy_price: float | None = 0.2,
    day_buy_price: float | None = 0.3,
) -> MagicMock:
    states = {}
    if sell_price is not None:
        states["sensor.morning_price"] = sell_price
        states["sensor.evening_price"] = sell_price
    if remaining is not None:
        states["sensor.pv_remaining"] = remaining
    if night_buy_price is not None:
        states["sensor.night_buy_window_internal"] = ("02:00", {"price": night_buy_price})
    if day_buy_price is not None:
        states["sensor.day_buy_window_internal"] = ("13:00", {"price": day_buy_price})
    return _hass_with_states({}, states)


@patch(_INTERNAL_SENSOR_PATCH, side_effect=_internal_sensor_id)
def test_morning_arbitrage_missing_sell_price(_mock_internal):
    """Returns (0.0, ...) with reason 'missing_morning_sell_price' when entity absent."""
    hass = _arb_hass(sell_price=None)
    kwh, details = _calculate_morning_arbitrage_kwh(
        hass,
        _arb_config(),
        entry_id="entry-1",
        forecasts=_forecasts(),
        bc=_bc(),
        sell_start_hour=10,
        current_soc=50.0,
        required_kwh=0.5,
    )
    assert kwh == 0.0
    assert details["arbitrage_reason"] == "missing_morning_sell_price"


@patch(_INTERNAL_SENSOR_PATCH, side_effect=_internal_sensor_id)
def test_morning_arbitrage_margin_below_threshold(_mock_internal):
    """Returns (0.0, ...) with reason 'margin_below_threshold'."""
    hass = _arb_hass(sell_price="0.4")  # below min_price=0.5
    kwh, details = _calculate_morning_arbitrage_kwh(
        hass,
        _arb_config(min_price=0.5),
        entry_id="entry-1",
        forecasts=_forecasts(),
        bc=_bc(),
        sell_start_hour=10,
        current_soc=50.0,
        required_kwh=0.5,
    )
    assert kwh == 0.0
    assert details["arbitrage_reason"] == "margin_below_threshold"
    assert details["sell_price"] == pytest.approx(0.4)
    assert details["buy_reference_price"] == pytest.approx(0.2)
    assert details["arbitrage_margin"] == pytest.approx(0.2)


@patch(_INTERNAL_SENSOR_PATCH, side_effect=_internal_sensor_id)
def test_morning_arbitrage_missing_buy_reference_price(_mock_internal):
    """Returns (0.0, ...) with reason 'missing_buy_reference_price'."""
    hass = _arb_hass(night_buy_price=None)
    kwh, details = _calculate_morning_arbitrage_kwh(
        hass,
        _arb_config(min_price=0.5),
        entry_id="entry-1",
        forecasts=_forecasts(),
        bc=_bc(),
        sell_start_hour=10,
        current_soc=50.0,
        required_kwh=0.5,
    )
    assert kwh == 0.0
    assert details["arbitrage_reason"] == "missing_buy_reference_price"


@patch(_INTERNAL_SENSOR_PATCH, side_effect=_internal_sensor_id)
def test_morning_arbitrage_missing_remaining_forecast(_mock_internal):
    """Returns (0.0, ...) with reason 'missing_remaining_forecast' when entity absent."""
    hass = _arb_hass(remaining=None)
    kwh, details = _calculate_morning_arbitrage_kwh(
        hass,
        _arb_config(),
        entry_id="entry-1",
        forecasts=_forecasts(),
        bc=_bc(),
        sell_start_hour=10,
        current_soc=50.0,
        required_kwh=0.5,
    )
    assert kwh == 0.0
    assert details["arbitrage_reason"] == "missing_remaining_forecast"


@patch(_INTERNAL_SENSOR_PATCH, side_effect=_internal_sensor_id)
def test_morning_arbitrage_invalid_remaining_forecast(_mock_internal):
    """Returns (0.0, ...) with reason 'invalid_remaining_forecast' when state non-numeric."""
    hass = _arb_hass(remaining="unavailable")
    kwh, details = _calculate_morning_arbitrage_kwh(
        hass,
        _arb_config(),
        entry_id="entry-1",
        forecasts=_forecasts(),
        bc=_bc(),
        sell_start_hour=10,
        current_soc=50.0,
        required_kwh=0.5,
    )
    assert kwh == 0.0
    assert details["arbitrage_reason"] == "invalid_remaining_forecast"


@patch(_INTERNAL_SENSOR_PATCH, side_effect=_internal_sensor_id)
def test_morning_arbitrage_arb_limit_zero(_mock_internal):
    """Returns (0.0, ...) with reason 'arb_limit_zero' when battery is full."""
    hass = _arb_hass(sell_price="1.0", remaining="3.0")
    kwh, details = _calculate_morning_arbitrage_kwh(
        hass,
        _arb_config(),
        entry_id="entry-1",
        forecasts=_forecasts(),
        bc=_bc(),
        sell_start_hour=10,
        current_soc=100.0,  # full
        required_kwh=0.0,
    )
    assert kwh == 0.0
    assert details["arbitrage_reason"] == "arb_limit_zero"
    assert "remaining_forecast_kwh" in details


@patch(_INTERNAL_SENSOR_PATCH, side_effect=_internal_sensor_id)
def test_morning_arbitrage_enabled(_mock_internal):
    """Returns arbitrage_kwh > 0 with reason 'enabled' when all conditions met."""
    # bc: 5 kWh; soc=50 -> 2.5 kWh; required=0.5 -> free_after=2.0; cap=2.0
    hass = _arb_hass(sell_price="1.0", remaining="2.0")
    kwh, details = _calculate_morning_arbitrage_kwh(
        hass,
        _arb_config(),
        entry_id="entry-1",
        forecasts=_forecasts(),
        bc=_bc(),
        sell_start_hour=10,
        current_soc=50.0,
        required_kwh=0.5,
    )
    assert kwh == pytest.approx(2.0)
    assert details["arbitrage_reason"] == "enabled"
    assert details["sell_price"] == pytest.approx(1.0)
    assert details["buy_reference_price"] == pytest.approx(0.2)
    assert details["arbitrage_margin"] == pytest.approx(0.8)
    assert details["remaining_forecast_kwh"] == pytest.approx(2.0)
    assert "arb_limit_kwh" in details
    assert "surplus_kwh" in details
    assert "free_after_kwh" in details
    assert "sell_window_start_hour" in details


# ---------------------------------------------------------------------------
# Integration test: arbitrage increases morning charge target SOC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(_INTERNAL_SENSOR_PATCH, side_effect=_internal_sensor_id)
async def test_morning_charge_arbitrage_increases_gap(
    _mock_internal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Morning charge logs higher gap_kwh when arbitrage is active."""
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.async_schedule_charge_completion",
        AsyncMock(),
    )
    base_config = {
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
        CONF_TEST_MODE: False,
    }
    base_states = {
        "number.prog2_soc": "50",
        "time.prog2_start": "04:00:00",
        "sensor.battery_soc": "50",
        "sensor.daily_load": "3",
        "sensor.tariff_end_hour": "13",
    }

    # Run without arbitrage config
    hass_no_arb = _hass_with_states(base_config, base_states)
    await async_run_morning_charge(hass_no_arb, entry_id="entry-1", margin=1.0)
    opt_no_arb = hass_no_arb.data[DOMAIN]["entry-1"]["last_optimization_sensor"]
    opt_no_arb.log_optimization.assert_called_once()
    _, details_no_arb = opt_no_arb.log_optimization.call_args.args

    # Run with arbitrage enabled
    arb_config = {
        **base_config,
        CONF_MORNING_MAX_PRICE_SENSOR: "sensor.morning_price",
        CONF_PV_FORECAST_REMAINING: "sensor.pv_remaining",
        CONF_MIN_ARBITRAGE_PRICE: 0.5,
    }
    arb_states = {
        **base_states,
        "sensor.morning_price": "1.0",
        "sensor.pv_remaining": "1.5",
        "sensor.night_buy_window_internal": ("02:00", {"price": 0.2}),
    }
    hass_arb = _hass_with_states(arb_config, arb_states)
    await async_run_morning_charge(hass_arb, entry_id="entry-1", margin=1.0)
    opt_arb = hass_arb.data[DOMAIN]["entry-1"]["last_optimization_sensor"]
    opt_arb.log_optimization.assert_called_once()
    _, details_arb = opt_arb.log_optimization.call_args.args

    # Arbitrage details must be present in the logged outcome
    assert "arbitrage_kwh" in details_arb, f"Missing arbitrage_kwh in details: {details_arb}"
    assert details_arb["arbitrage_kwh"] > 0, f"arbitrage_kwh should be >0, got {details_arb['arbitrage_kwh']}"
    assert details_arb.get("arbitrage_reason") == "enabled", f"Unexpected reason: {details_arb.get('arbitrage_reason')}"

    # Without arbitrage, details should NOT contain arbitrage_kwh
    assert details_no_arb.get("arbitrage_kwh", 0.0) == 0.0


@patch(_INTERNAL_SENSOR_PATCH, side_effect=_internal_sensor_id)
def test_resolve_arbitrage_margin_gate_for_day_window(_mock_internal):
    """Shared helper should resolve day buy window margin details."""
    hass = _arb_hass(sell_price="0.9", day_buy_price=0.3)
    margin_ok, details = resolve_arbitrage_margin_gate(
        hass,
        entry_id="entry-1",
        sell_price=0.9,
        min_arbitrage_price=0.2,
        buy_reference_unique_id_suffix="day_buy_window",
        buy_reference_entity_name="Day buy window",
    )

    assert margin_ok is True
    assert details["buy_reference_price"] == pytest.approx(0.3)
    assert details["arbitrage_margin"] == pytest.approx(0.6)


@patch(_INTERNAL_SENSOR_PATCH, side_effect=_internal_sensor_id)
def test_resolve_arbitrage_margin_gate_rounds_price_details(_mock_internal):
    """Shared helper should round price diagnostics to two decimal places."""
    hass = _arb_hass(day_buy_price=0.465)
    margin_ok, details = resolve_arbitrage_margin_gate(
        hass,
        entry_id="entry-1",
        sell_price=1.2,
        min_arbitrage_price=0.1,
        buy_reference_unique_id_suffix="day_buy_window",
        buy_reference_entity_name="Day buy window",
    )

    assert margin_ok is True
    assert details["sell_price"] == 1.2
    assert details["buy_reference_price"] == 0.47
    assert details["arbitrage_margin"] == 0.73


@patch(_INTERNAL_SENSOR_PATCH, side_effect=_internal_sensor_id)
def test_afternoon_arbitrage_fails_closed_without_buy_reference(_mock_internal):
    """Afternoon arbitrage should fail closed when the day buy window is unavailable."""
    hass = _arb_hass(day_buy_price=None)
    kwh, details = _calculate_arbitrage_kwh(
        hass,
        _afternoon_arb_config(min_price=0.2),
        forecasts=_forecasts(start_hour=15, end_hour=22),
        bc=_bc(),
        sell_start_hour=18,
        current_soc=50.0,
        required_kwh=0.5,
        entry_id="entry-1",
    )

    assert kwh == 0.0
    assert details["arbitrage_reason"] == "missing_buy_reference_price"
