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


def calculate_required_energy_windowed(
    start_hour: int,
    end_hour: int,
    config: dict,
    hass_states_get: any,
    efficiency: float,
    margin: float = 1.1,
    include_tomorrow: bool = False,
    current_hour: int | None = None,
    current_minute: int | None = None,
) -> float:
    """Calculate required energy using time-windowed data with dynamic adjustment.
    
    This is the sophisticated multi-component calculation that accounts for:
    - Time-specific usage patterns (different rates for different hours)
    - Dynamic usage ratio (adjusts if today's consumption is higher)
    - Separate loss tracking
    - Cross-midnight period support
    
    Args:
        start_hour: Starting hour (0-23)
        end_hour: Ending hour (0-23, can be < start_hour for cross-midnight)
        config: Integration config dictionary
        hass_states_get: Function to get entity state
        efficiency: Battery efficiency (%)
        margin: Safety margin multiplier (default 1.1)
        include_tomorrow: True for cross-midnight periods like 22:00-06:00
        current_hour: Current hour for dynamic ratio calculation
        current_minute: Current minute for dynamic ratio calculation
        
    Returns:
        Required energy (kWh)
        
    Example:
        Evening 18:00-22:00 on cold day:
        - Time-windowed base: 10.6 kWh
        - Dynamic ratio: 1.15
        - Losses: 1.38 kWh
        - Heat pump: 3.2 kWh
        - Total: 18.58 kWh (vs 8.0 kWh simple calculation)
    """
    from .utils import build_hourly_usage_array, calculate_dynamic_usage_ratio
    from ..const import CONF_DAILY_LOSSES_SENSOR
    
    # Build 24-hour usage array from time windows
    hourly_usage = build_hourly_usage_array(config, hass_states_get)
    
    # Extract relevant hours for this period
    if include_tomorrow and end_hour < start_hour:
        # Cross-midnight: e.g., 22:00-06:00 → hours [22,23,0,1,2,3,4,5]
        period_usage = hourly_usage[start_hour:] + hourly_usage[:end_hour]
        hours_count = (24 - start_hour) + end_hour
    else:
        # Normal period: e.g., 18:00-22:00 → hours [18,19,20,21]
        period_usage = hourly_usage[start_hour:end_hour]
        hours_count = end_hour - start_hour
    
    if hours_count == 0:
        return 0.0
    
    # Calculate base usage for period
    base_usage = sum(period_usage)
    
    # Apply dynamic usage ratio if available
    if current_hour is not None and current_minute is not None:
        usage_ratio = calculate_dynamic_usage_ratio(
            config, hass_states_get, current_hour, current_minute
        )
    else:
        usage_ratio = 1.0
    
    adjusted_usage = base_usage * usage_ratio
    
    # Account for efficiency losses
    if efficiency == 0:
        return 0.0
    usage_with_losses = adjusted_usage / (efficiency / 100.0)
    
    # Apply safety margin
    usage_required = usage_with_losses * margin
    
    # Add separate loss component (inverter/system losses)
    losses_sensor = config.get(CONF_DAILY_LOSSES_SENSOR)
    if losses_sensor:
        losses_state = hass_states_get(losses_sensor)
        if losses_state and losses_state.state not in (None, "unknown", "unavailable"):
            try:
                daily_losses = float(losses_state.state)
                hourly_losses = daily_losses / 24.0
                period_losses = hourly_losses * hours_count * margin
                usage_required += period_losses
            except (ValueError, TypeError):
                pass
    
    return usage_required