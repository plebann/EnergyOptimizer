"""Energy balance calculations for Energy Optimizer."""
from __future__ import annotations

from typing import Any

from ..const import CONF_DAILY_LOSSES_SENSOR
from ..helpers import get_float_value


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


def calculate_losses(
    hass: Any,
    config: dict[str, object],
    *,
    hours_morning: int,
    margin: float,
) -> tuple[float, float]:
    """Calculate hourly and total losses for a given window."""
    losses_hourly = 0.0
    losses_entity = config.get(CONF_DAILY_LOSSES_SENSOR)
    if losses_entity:
        daily_losses = get_float_value(hass, losses_entity, default=0.0)
        if daily_losses:
            losses_hourly = (daily_losses / 24.0) * margin

    return losses_hourly, losses_hourly * hours_morning


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
        (hourly_usage[hour] + heat_pump_hourly.get(hour, 0.0)) * margin
        + losses_hourly
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
    required_kwh = sum(
        hourly_demand(
            hour,
            hourly_usage=hourly_usage,
            heat_pump_hourly=heat_pump_hourly,
            losses_hourly=losses_hourly,
            margin=margin,
        )
        for hour in range(start_hour, end_hour)
    )

    sufficiency_hour: int | None = None
    for hour in range(start_hour, end_hour):
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

    required_sufficiency_kwh = sum(
        hourly_demand(
            hour,
            hourly_usage=hourly_usage,
            heat_pump_hourly=heat_pump_hourly,
            losses_hourly=losses_hourly,
            margin=margin,
        )
        for hour in range(start_hour, sufficiency_hour)
    )
    pv_sufficiency_kwh = sum(
        pv_forecast_hourly.get(hour, 0.0)
        for hour in range(start_hour, sufficiency_hour)
    )

    return (
        required_kwh,
        required_sufficiency_kwh,
        pv_sufficiency_kwh,
        sufficiency_hour,
        sufficiency_reached,
    )