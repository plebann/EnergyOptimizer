"""Energy balance calculations for Energy Optimizer."""
from __future__ import annotations

from .battery import kwh_to_soc


def calculate_required_energy(
    hourly_usage: float, hours: int, efficiency: float, margin: float = 1.1
) -> float:
    """Calculate required energy for time period with losses and margin.
    
    Args:
        hourly_usage: Average hourly usage (kWh)
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


def calculate_usage_ratio(daily_energy: float, hours_in_period: int) -> float:
    """Calculate hourly usage ratio from daily energy.
    
    Args:
        daily_energy: Total daily energy usage (kWh)
        hours_in_period: Number of hours in the period
        
    Returns:
        Average hourly usage (kWh/h)
    """
    if hours_in_period == 0:
        return 0.0
    
    # Assume 24-hour day
    hourly_average = daily_energy / 24.0
    
    # Scale to period
    return hourly_average


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


def calculate_energy_deficit(
    battery_space: float, required_energy: float, pv_forecast: float = 0.0
) -> float:
    """Calculate energy deficit that needs to be charged.
    
    Args:
        battery_space: Available battery space (kWh)
        required_energy: Required energy for period (kWh)
        pv_forecast: Expected PV generation (kWh)
        
    Returns:
        Energy deficit to charge (kWh)
    """
    # Account for PV forecast reducing requirement
    net_required = required_energy - pv_forecast
    net_required = max(0.0, net_required)
    
    # Deficit is what we need beyond current reserve
    # Since this is called when we have deficit, we assume battery_space represents capacity
    deficit = net_required
    
    # Can't charge more than available space
    return min(deficit, battery_space)


def calculate_target_soc_for_deficit(
    current_soc: float,
    deficit_kwh: float,
    capacity_ah: float,
    voltage: float,
    max_soc: float,
) -> float:
    """Calculate target SOC to cover energy deficit.
    
    Args:
        current_soc: Current state of charge (%)
        deficit_kwh: Energy deficit to cover (kWh)
        capacity_ah: Battery capacity (Ah)
        voltage: Battery voltage (V)
        max_soc: Maximum allowed SOC (%)
        
    Returns:
        Target SOC (%)
    """
    # Calculate SOC increase needed
    soc_increase = kwh_to_soc(deficit_kwh, capacity_ah, voltage)
    
    # Calculate target SOC
    target_soc = current_soc + soc_increase
    
    # Clamp to max SOC
    return min(target_soc, max_soc)


def calculate_required_energy_with_heat_pump(
    base_usage: float,
    hours: int,
    efficiency: float,
    heat_pump_consumption: float = 0.0,
    margin: float = 1.1,
) -> float:
    """Calculate required energy including heat pump consumption.
    
    Args:
        base_usage: Base hourly usage without heat pump (kWh)
        hours: Number of hours in period
        efficiency: Battery efficiency (%)
        heat_pump_consumption: Heat pump consumption for period (kWh)
        margin: Safety margin multiplier
        
    Returns:
        Total required energy (kWh)
    """
    # Calculate base required energy
    base_required = calculate_required_energy(base_usage, hours, efficiency, margin)
    
    # Add heat pump consumption (already includes losses)
    total_required = base_required + heat_pump_consumption
    
    return total_required
