"""Forecast aggregation helpers for Energy Optimizer."""
from __future__ import annotations

from typing import Any

from .heat_pump import get_heat_pump_forecast
from .pv_forecast import get_pv_forecast
from .time_window import build_hour_window


async def async_get_forecasts(
    hass: Any,
    config: dict[str, object],
    *,
    start_hour: int,
    end_hour: int,
    apply_pv_efficiency: bool = True,
    pv_compensate: bool = False,
    entry_id: str | None = None,
) -> tuple[float, dict[int, float], float, dict[int, float]]:
    """Fetch heat pump + PV forecasts for the given window."""
    hours_morning = max(len(build_hour_window(start_hour, end_hour)), 1)

    heat_pump_kwh, heat_pump_hourly = await get_heat_pump_forecast(
        hass, config, starting_hour=start_hour, hours_ahead=hours_morning
    )

    pv_forecast_kwh, pv_forecast_hourly = get_pv_forecast(
        hass,
        config,
        start_hour=start_hour,
        end_hour=end_hour,
        apply_efficiency=apply_pv_efficiency,
        compensate=pv_compensate,
        entry_id=entry_id,
    )

    return heat_pump_kwh, heat_pump_hourly, pv_forecast_kwh, pv_forecast_hourly
