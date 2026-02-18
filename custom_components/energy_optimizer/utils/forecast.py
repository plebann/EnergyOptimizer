"""Forecast aggregation helpers for Energy Optimizer."""
from __future__ import annotations

from typing import Any

from .heat_pump import get_heat_pump_forecast
from .pv_forecast import get_pv_forecast
from .time_window import build_hour_window


async def get_heat_pump_forecast_window(
    hass: Any,
    config: dict[str, object],
    *,
    start_hour: int,
    end_hour: int,
) -> tuple[float, dict[int, float]]:
    """Return heat pump forecast for a window, respecting wrap."""
    hours_ahead = max(len(build_hour_window(start_hour, end_hour)), 1)
    return await get_heat_pump_forecast(
        hass, config, starting_hour=start_hour, hours_ahead=hours_ahead
    )


def get_pv_forecast_window(
    hass: Any,
    config: dict[str, object],
    *,
    start_hour: int,
    end_hour: int,
    apply_efficiency: bool = True,
    compensate: bool = False,
    entry_id: str | None = None,
) -> tuple[float, dict[int, float]]:
    """Return PV forecast for a window, with optional efficiency/compensation."""
    return get_pv_forecast(
        hass,
        config,
        start_hour=start_hour,
        end_hour=end_hour,
        apply_efficiency=apply_efficiency,
        compensate=compensate,
        entry_id=entry_id,
    )
