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
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_MORNING_MAX_PRICE_SENSOR,
    CONF_PROG2_SOC_ENTITY,
    CONF_PV_FORECAST_REMAINING,
    CONF_TARIFF_END_HOUR_SENSOR,
    CONF_TEST_MODE,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.common import (
    BatteryConfig,
    ForecastData,
    _compute_arbitrage_from_cap,
)
from custom_components.energy_optimizer.decision_engine.morning_charge import (
    _calculate_morning_arbitrage_kwh,
    async_run_morning_charge,
)

pytestmark = pytest.mark.enable_socket


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bc(capacity_ah: float = 100.0, voltage: float = 50.0) -> BatteryConfig:
    return BatteryConfig(
        capacity_ah=capacity_ah,
        voltage=voltage,
        min_soc=10.0,
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


def _arb_hass(
    sell_price: str | None = "0.8",
    remaining: str | None = "3.0",
) -> MagicMock:
    states = {}
    if sell_price is not None:
        states["sensor.morning_price"] = sell_price
    if remaining is not None:
        states["sensor.pv_remaining"] = remaining
    return _hass_with_states({}, states)


def test_morning_arbitrage_missing_sell_price():
    """Returns (0.0, ...) with reason 'missing_morning_sell_price' when entity absent."""
    hass = _arb_hass(sell_price=None)
    kwh, details = _calculate_morning_arbitrage_kwh(
        hass,
        _arb_config(),
        forecasts=_forecasts(),
        bc=_bc(),
        sell_start_hour=10,
        current_soc=50.0,
        required_kwh=0.5,
    )
    assert kwh == 0.0
    assert details["arbitrage_reason"] == "missing_morning_sell_price"


def test_morning_arbitrage_sell_price_below_threshold():
    """Returns (0.0, ...) with reason 'sell_price_below_threshold'."""
    hass = _arb_hass(sell_price="0.4")  # below min_price=0.5
    kwh, details = _calculate_morning_arbitrage_kwh(
        hass,
        _arb_config(min_price=0.5),
        forecasts=_forecasts(),
        bc=_bc(),
        sell_start_hour=10,
        current_soc=50.0,
        required_kwh=0.5,
    )
    assert kwh == 0.0
    assert details["arbitrage_reason"] == "sell_price_below_threshold"
    assert details["sell_price"] == pytest.approx(0.4)


def test_morning_arbitrage_missing_remaining_forecast():
    """Returns (0.0, ...) with reason 'missing_remaining_forecast' when entity absent."""
    hass = _arb_hass(remaining=None)
    kwh, details = _calculate_morning_arbitrage_kwh(
        hass,
        _arb_config(),
        forecasts=_forecasts(),
        bc=_bc(),
        sell_start_hour=10,
        current_soc=50.0,
        required_kwh=0.5,
    )
    assert kwh == 0.0
    assert details["arbitrage_reason"] == "missing_remaining_forecast"


def test_morning_arbitrage_invalid_remaining_forecast():
    """Returns (0.0, ...) with reason 'invalid_remaining_forecast' when state non-numeric."""
    hass = _arb_hass(remaining="unavailable")
    kwh, details = _calculate_morning_arbitrage_kwh(
        hass,
        _arb_config(),
        forecasts=_forecasts(),
        bc=_bc(),
        sell_start_hour=10,
        current_soc=50.0,
        required_kwh=0.5,
    )
    assert kwh == 0.0
    assert details["arbitrage_reason"] == "invalid_remaining_forecast"


def test_morning_arbitrage_arb_limit_zero():
    """Returns (0.0, ...) with reason 'arb_limit_zero' when battery is full."""
    hass = _arb_hass(sell_price="1.0", remaining="3.0")
    kwh, details = _calculate_morning_arbitrage_kwh(
        hass,
        _arb_config(),
        forecasts=_forecasts(),
        bc=_bc(),
        sell_start_hour=10,
        current_soc=100.0,  # full
        required_kwh=0.0,
    )
    assert kwh == 0.0
    assert details["arbitrage_reason"] == "arb_limit_zero"
    assert "remaining_forecast_kwh" in details


def test_morning_arbitrage_enabled():
    """Returns arbitrage_kwh > 0 with reason 'enabled' when all conditions met."""
    # bc: 5 kWh; soc=50 -> 2.5 kWh; required=0.5 -> free_after=2.0; cap=2.0
    hass = _arb_hass(sell_price="1.0", remaining="2.0")
    kwh, details = _calculate_morning_arbitrage_kwh(
        hass,
        _arb_config(),
        forecasts=_forecasts(),
        bc=_bc(),
        sell_start_hour=10,
        current_soc=50.0,
        required_kwh=0.5,
    )
    assert kwh == pytest.approx(2.0)
    assert details["arbitrage_reason"] == "enabled"
    assert details["sell_price"] == pytest.approx(1.0)
    assert details["remaining_forecast_kwh"] == pytest.approx(2.0)
    assert "arb_limit_kwh" in details
    assert "surplus_kwh" in details
    assert "free_after_kwh" in details
    assert "sell_window_start_hour" in details


# ---------------------------------------------------------------------------
# Integration test: arbitrage increases morning charge target SOC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_morning_charge_arbitrage_increases_gap() -> None:
    """Morning charge logs higher gap_kwh when arbitrage is active."""
    base_config = {
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
        CONF_DAILY_LOAD_SENSOR: "sensor.daily_load",
        CONF_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end_hour",
        CONF_BATTERY_CAPACITY_AH: 100,
        CONF_BATTERY_VOLTAGE: 50,
        CONF_MIN_SOC: 10,
        CONF_MAX_SOC: 100,
        CONF_BATTERY_EFFICIENCY: 100,
        CONF_TEST_MODE: False,
    }
    base_states = {
        "number.prog2_soc": "50",
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
