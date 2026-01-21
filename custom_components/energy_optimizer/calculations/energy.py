"""Energy balance calculations for Energy Optimizer."""
from __future__ import annotations


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