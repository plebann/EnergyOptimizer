"""Heat pump estimation calculations for Energy Optimizer."""
from __future__ import annotations

from .utils import interpolate


def interpolate_cop(temperature: float, cop_curve: list[tuple[float, float]]) -> float:
    """Interpolate COP from temperature using COP curve.
    
    Args:
        temperature: Outside temperature (°C)
        cop_curve: List of (temperature, COP) tuples
        
    Returns:
        Interpolated COP value
    """
    return interpolate(temperature, cop_curve)


def estimate_daily_consumption(
    min_temp: float,
    max_temp: float,
    avg_temp: float,
    cop_curve: list[tuple[float, float]],
    base_heating_demand: float = 50.0,
) -> float:
    """Estimate daily heat pump consumption based on temperature.
    
    Uses degree-days method for estimation.
    
    Args:
        min_temp: Minimum daily temperature (°C)
        max_temp: Maximum daily temperature (°C)
        avg_temp: Average daily temperature (°C)
        cop_curve: List of (temperature, COP) tuples
        base_heating_demand: Base heating demand (kWh) at reference temperature
        
    Returns:
        Estimated daily consumption (kWh)
    """
    # Base temperature for heating (typically 18°C for comfort)
    base_temperature = 18.0
    
    # Calculate heating hours based on temperature
    heating_hours = calculate_heating_hours(min_temp, max_temp, base_temperature)
    
    if heating_hours == 0:
        return 0.0
    
    # Calculate average COP at average temperature
    avg_cop = interpolate_cop(avg_temp, cop_curve)
    
    if avg_cop == 0:
        return 0.0
    
    # Calculate heating degree-days
    if avg_temp >= base_temperature:
        return 0.0
    
    degree_days = (base_temperature - avg_temp) * (heating_hours / 24.0)
    
    # Estimate consumption based on degree-days
    # Scale base demand by degree-days and COP
    daily_consumption = (base_heating_demand * degree_days / 10.0) / avg_cop
    
    return max(0.0, daily_consumption)


def calculate_heating_hours(
    min_temp: float, max_temp: float, base_temperature: float = 18.0
) -> int:
    """Calculate estimated heating hours based on temperature range.
    
    Args:
        min_temp: Minimum daily temperature (°C)
        max_temp: Maximum daily temperature (°C)
        base_temperature: Base temperature for heating (°C)
        
    Returns:
        Estimated heating hours
    """
    avg_temp = (min_temp + max_temp) / 2.0
    
    # If average temp is above base, no heating needed
    if avg_temp >= base_temperature:
        return 0
    
    # If max temp is below base, heat all day
    if max_temp < base_temperature:
        return 24
    
    # Partial heating - estimate hours based on temperature range
    temp_range = max_temp - min_temp
    if temp_range == 0:
        return 24
    
    # Linear approximation of heating hours
    heating_fraction = (base_temperature - avg_temp) / temp_range
    heating_hours = int(24 * min(1.0, max(0.0, heating_fraction)))
    
    return heating_hours


def calculate_peak_consumption(
    min_temp: float, cop_curve: list[tuple[float, float]], rated_power: float = 2.5
) -> float:
    """Calculate peak heat pump power consumption.
    
    Args:
        min_temp: Minimum temperature (°C)
        cop_curve: List of (temperature, COP) tuples
        rated_power: Rated heating power (kW)
        
    Returns:
        Peak electrical consumption (kW)
    """
    # COP at minimum temperature
    cop_at_min = interpolate_cop(min_temp, cop_curve)
    
    if cop_at_min == 0:
        return 0.0
    
    # Peak electrical power = Heating power / COP
    return rated_power / cop_at_min
