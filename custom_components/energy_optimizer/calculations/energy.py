"""Energy balance calculations for Energy Optimizer."""
from __future__ import annotations

from typing import Any

from ..const import CONF_DAILY_LOSSES_SENSOR
from ..helpers import get_float_value
from ..utils.time_window import build_hour_window


def calculate_required_energy(
    hourly_usage: float, hourly_losses: float, hours: int, efficiency: float, margin: float = 1.1
) -> float:
    """Calculate required energy for time period with losses and margin.
    
    Args:
        hourly_usage: Average hourly usage (kWh)
        hourly_losses: Average hourly losses (kWh)
        hours: Number of hours in period
        efficiency: Battery efficiency (%)
        margin: Safety margin multiplier (default 1.1 = 10%)
        
    Returns:
        Required energy (kWh)
    """
    if efficiency == 0:
        return 0.0
    
    # Calculate base usage
    base_energy = hourly_usage * hours
    
    # Account for efficiency losses
    energy_with_losses = base_energy / (efficiency / 100.0)
    
    # Apply safety margin
    return energy_with_losses * margin


def calculate_surplus_energy(
    battery_reserve: float, required_energy: float, pv_forecast: float = 0.0
) -> float:
    """Calculate available surplus energy above requirements.
    
    Args:
        battery_reserve: Available battery reserve (kWh)
        required_energy: Required energy for period (kWh)
        pv_forecast: Expected PV generation (kWh)
        
    Returns:
        Surplus energy available (kWh)
    """
    available_energy = battery_reserve + pv_forecast
    surplus = available_energy - required_energy
    
    # Return 0 if no surplus
    return max(0.0, surplus)


def calculate_needed_reserve(
    required_kwh: float,
    pv_forecast_kwh: float,
) -> float:
    """Calculate needed battery reserve for a period.

    This calculation is demand-first and does not use current battery reserve.

    Args:
        required_kwh: Total demand in the window (kWh).
        pv_forecast_kwh: Forecast PV generation in the window (kWh).

    Returns:
        Required reserve that battery must provide (kWh).
    """
    return max(required_kwh - pv_forecast_kwh, 0.0)


def calculate_needed_reserve_sufficiency(
    required_sufficiency_kwh: float,
    pv_sufficiency_kwh: float,
) -> float:
    """Calculate needed reserve until PV sufficiency point."""
    return max(required_sufficiency_kwh - pv_sufficiency_kwh, 0.0)


def calculate_losses(
    hass: Any,
    config: dict[str, object],
    *,
    hours: int,
    margin: float,
) -> tuple[float, float]:
    """Calculate hourly and total losses for a given window."""
    losses_hourly = 0.0
    losses_entity = config.get(CONF_DAILY_LOSSES_SENSOR)
    if losses_entity:
        daily_losses = get_float_value(hass, losses_entity, default=0.0)
        if daily_losses:
            losses_hourly = (daily_losses / 24.0) * margin

    return losses_hourly, losses_hourly * hours


def hourly_demand(
    hour: int,
    *,
    hourly_usage: list[float],
    heat_pump_hourly: dict[int, float],
    losses_hourly: float,
    margin: float,
) -> float:
    """Calculate hourly demand including heat pump and losses."""
    return (
        (hourly_usage[hour] + heat_pump_hourly.get(hour, 0.0) + losses_hourly) * margin
    )


def calculate_sufficiency_window(
    *,
    start_hour: int,
    end_hour: int,
    hourly_usage: list[float],
    heat_pump_hourly: dict[int, float],
    losses_hourly: float,
    margin: float,
    pv_forecast_hourly: dict[int, float],
) -> tuple[float, float, float, int, bool]:
    """Calculate required energy and PV sufficiency window details."""
    hour_window = build_hour_window(start_hour, end_hour)
    required_kwh = sum(
        hourly_demand(
            hour,
            hourly_usage=hourly_usage,
            heat_pump_hourly=heat_pump_hourly,
            losses_hourly=losses_hourly,
            margin=margin,
        )
        for hour in hour_window
    )

    sufficiency_hour: int | None = None
    for hour in hour_window:
        if pv_forecast_hourly.get(hour, 0.0) >= hourly_demand(
            hour,
            hourly_usage=hourly_usage,
            heat_pump_hourly=heat_pump_hourly,
            losses_hourly=losses_hourly,
            margin=margin,
        ):
            sufficiency_hour = hour
            break

    sufficiency_reached = sufficiency_hour is not None
    if sufficiency_hour is None:
        sufficiency_hour = end_hour

    required_sufficiency_kwh = 0.0
    pv_sufficiency_kwh = 0.0
    for hour in hour_window:
        if sufficiency_reached and hour == sufficiency_hour:
            break
        required_sufficiency_kwh += hourly_demand(
            hour,
            hourly_usage=hourly_usage,
            heat_pump_hourly=heat_pump_hourly,
            losses_hourly=losses_hourly,
            margin=margin,
        )
        pv_sufficiency_kwh += pv_forecast_hourly.get(hour, 0.0)

    return (
        required_kwh,
        required_sufficiency_kwh,
        pv_sufficiency_kwh,
        sufficiency_hour,
        sufficiency_reached,
    )