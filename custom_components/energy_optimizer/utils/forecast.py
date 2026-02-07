"""Forecast aggregation helpers for Energy Optimizer."""
from __future__ import annotations

from typing import Any

from .heat_pump import async_fetch_heat_pump_forecast_details
from .pv_forecast import get_pv_forecast_hourly_kwh, get_pv_forecast_kwh


def _build_uniform_heat_pump_hourly(
    heat_pump_kwh: float,
    *,
    start_hour: int,
    end_hour: int,
) -> dict[int, float]:
    hours_morning = max(end_hour - start_hour, 1)
    if heat_pump_kwh <= 0 or hours_morning <= 0:
        return {}
    per_hour = heat_pump_kwh / hours_morning
    return {hour: per_hour for hour in range(start_hour, end_hour)}

async def async_get_forecasts(
    hass: Any,
    config: dict[str, object],
    *,
    start_hour: int,
    end_hour: int,
) -> tuple[float, dict[int, float], float, dict[int, float]]:
    """Fetch heat pump + PV forecasts for the given window."""
    hours_morning = max(end_hour - start_hour, 1)
    heat_pump_kwh, heat_pump_hourly = await async_fetch_heat_pump_forecast_details(
        hass, config, starting_hour=start_hour, hours_ahead=hours_morning
    )
    if not heat_pump_hourly and heat_pump_kwh and hours_morning > 0:
        heat_pump_hourly = _build_uniform_heat_pump_hourly(
            heat_pump_kwh, start_hour=start_hour, end_hour=end_hour
        )

    pv_forecast_kwh = get_pv_forecast_kwh(
        hass,
        config,
        start_hour=start_hour,
        end_hour=end_hour,
    )
    pv_forecast_hourly = get_pv_forecast_hourly_kwh(
        hass,
        config,
        start_hour=start_hour,
        end_hour=end_hour,
    )

    return heat_pump_kwh, heat_pump_hourly, pv_forecast_kwh, pv_forecast_hourly
