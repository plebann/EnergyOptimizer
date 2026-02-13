"""Tests for hour window handling across midnight."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.energy_optimizer.calculations.energy import (
    calculate_sufficiency_window,
)
from custom_components.energy_optimizer.const import (
    CONF_ENABLE_HEAT_PUMP,
    CONF_HEAT_PUMP_FORECAST_DOMAIN,
    CONF_HEAT_PUMP_FORECAST_SERVICE,
    CONF_PV_FORECAST_TODAY,
    CONF_PV_FORECAST_TOMORROW,
    DEFAULT_HEAT_PUMP_FORECAST_DOMAIN,
    DEFAULT_HEAT_PUMP_FORECAST_SERVICE,
)
from custom_components.energy_optimizer.utils.heat_pump import (
    get_heat_pump_forecast,
)
from custom_components.energy_optimizer.utils.pv_forecast import (
    get_pv_forecast,
)
from custom_components.energy_optimizer.utils.time_window import build_hour_window


@pytest.mark.unit
def test_build_hour_window_wraps_midnight() -> None:
    assert build_hour_window(22, 4) == [22, 23, 0, 1, 2, 3]


@pytest.mark.unit
def test_build_hour_window_same_day() -> None:
    assert build_hour_window(6, 10) == [6, 7, 8, 9]


@pytest.mark.unit
def test_pv_forecast_wraps_midnight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dt_util,
        "now",
        lambda: datetime(2026, 2, 6, 12, 0, tzinfo=timezone.utc),
    )
    hass = MagicMock()
    pv_today_state = MagicMock()
    pv_today_state.attributes = {
        "detailedForecast": [
            {"period_start": "2026-02-06T23:00:00+01:00", "pv_estimate": 1.0},
        ]
    }
    pv_tomorrow_state = MagicMock()
    pv_tomorrow_state.attributes = {
        "detailedForecast": [
            {"period_start": "2026-02-07T01:00:00+01:00", "pv_estimate": 2.0},
            {"period_start": "2026-02-07T05:00:00+01:00", "pv_estimate": 3.0},
        ]
    }
    hass.states.get.side_effect = lambda entity_id: {
        "sensor.pv_today": pv_today_state,
        "sensor.pv_tomorrow": pv_tomorrow_state,
    }.get(entity_id)

    config = {
        CONF_PV_FORECAST_TODAY: "sensor.pv_today",
        CONF_PV_FORECAST_TOMORROW: "sensor.pv_tomorrow",
    }
    _, hourly = get_pv_forecast(
        hass,
        config,
        start_hour=22,
        end_hour=4,
        apply_efficiency=False,
    )

    assert set(hourly.keys()) == {22, 23, 0, 1, 2, 3}
    assert hourly[23] == pytest.approx(1.0)
    assert hourly[1] == pytest.approx(2.0)
    assert hourly[22] == pytest.approx(0.0)
    assert 5 not in hourly


@pytest.mark.asyncio
async def test_heat_pump_forecast_wraps_midnight() -> None:
    hass = MagicMock()
    hass.services.has_service.return_value = True
    hass.services.async_call = AsyncMock(
        return_value={
            "total_energy_kwh": 6.0,
            "hours": [
                {"datetime": "2026-02-06T23:00:00+01:00", "energy_kwh": 1.0},
                {"datetime": "2026-02-07T01:00:00+01:00", "energy_kwh": 2.0},
                {"datetime": "2026-02-07T05:00:00+01:00", "energy_kwh": 3.0},
            ],
        }
    )
    config = {
        CONF_ENABLE_HEAT_PUMP: True,
        CONF_HEAT_PUMP_FORECAST_DOMAIN: DEFAULT_HEAT_PUMP_FORECAST_DOMAIN,
        CONF_HEAT_PUMP_FORECAST_SERVICE: DEFAULT_HEAT_PUMP_FORECAST_SERVICE,
    }

    total_kwh, hourly_kwh = await get_heat_pump_forecast(
        hass, config, starting_hour=22, hours_ahead=6
    )

    assert total_kwh == pytest.approx(6.0)
    assert set(hourly_kwh.keys()) == {23, 1}
    assert hourly_kwh[23] == pytest.approx(1.0)
    assert hourly_kwh[1] == pytest.approx(2.0)


@pytest.mark.unit
def test_calculate_sufficiency_window_wraps_midnight() -> None:
    hourly_usage = [1.0] * 24
    heat_pump_hourly: dict[int, float] = {}
    pv_forecast_hourly = {23: 0.5, 0: 2.0}

    (
        required_kwh,
        required_sufficiency_kwh,
        pv_sufficiency_kwh,
        sufficiency_hour,
        sufficiency_reached,
    ) = calculate_sufficiency_window(
        start_hour=22,
        end_hour=4,
        hourly_usage=hourly_usage,
        heat_pump_hourly=heat_pump_hourly,
        losses_hourly=0.0,
        margin=1.0,
        pv_forecast_hourly=pv_forecast_hourly,
    )

    assert required_kwh == pytest.approx(6.0)
    assert required_sufficiency_kwh == pytest.approx(2.0)
    assert pv_sufficiency_kwh == pytest.approx(0.5)
    assert sufficiency_hour == 0
    assert sufficiency_reached is True
