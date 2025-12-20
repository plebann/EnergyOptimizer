"""Battery calculations for Energy Optimizer."""
from __future__ import annotations


def soc_to_kwh(soc: float, capacity_ah: float, voltage: float) -> float:
    """Convert SOC percentage to kWh energy.
    
    Args:
        soc: State of charge (%)
        capacity_ah: Battery capacity (Ah)
        voltage: Battery voltage (V)
        
    Returns:
        Energy in kWh
    """
    return (soc / 100.0) * capacity_ah * voltage / 1000.0


def kwh_to_soc(kwh: float, capacity_ah: float, voltage: float) -> float:
    """Convert kWh energy to SOC percentage.
    
    Args:
        kwh: Energy (kWh)
        capacity_ah: Battery capacity (Ah)
        voltage: Battery voltage (V)
        
    Returns:
        State of charge (%)
    """
    if capacity_ah == 0 or voltage == 0:
        return 0.0
    return (kwh * 1000.0) / (capacity_ah * voltage) * 100.0


def calculate_battery_reserve(
    current_soc: float, min_soc: float, capacity_ah: float, voltage: float
) -> float:
    """Calculate available battery reserve above minimum SOC.
    
    Args:
        current_soc: Current state of charge (%)
        min_soc: Minimum allowed SOC (%)
        capacity_ah: Battery capacity (Ah)
        voltage: Battery voltage (V)
        
    Returns:
        Available reserve energy (kWh)
    """
    if current_soc <= min_soc:
        return 0.0
    
    reserve_soc = current_soc - min_soc
    return soc_to_kwh(reserve_soc, capacity_ah, voltage)


def calculate_battery_space(
    current_soc: float, max_soc: float, capacity_ah: float, voltage: float
) -> float:
    """Calculate available battery space below maximum SOC.
    
    Args:
        current_soc: Current state of charge (%)
        max_soc: Maximum allowed SOC (%)
        capacity_ah: Battery capacity (Ah)
        voltage: Battery voltage (V)
        
    Returns:
        Available space for charging (kWh)
    """
    if current_soc >= max_soc:
        return 0.0
    
    space_soc = max_soc - current_soc
    return soc_to_kwh(space_soc, capacity_ah, voltage)


def calculate_usable_capacity(
    capacity_ah: float, voltage: float, min_soc: float, max_soc: float
) -> float:
    """Calculate usable battery capacity between min and max SOC.
    
    Args:
        capacity_ah: Battery capacity (Ah)
        voltage: Battery voltage (V)
        min_soc: Minimum allowed SOC (%)
        max_soc: Maximum allowed SOC (%)
        
    Returns:
        Usable capacity (kWh)
    """
    usable_soc = max_soc - min_soc
    return soc_to_kwh(usable_soc, capacity_ah, voltage)


def calculate_total_capacity(capacity_ah: float, voltage: float) -> float:
    """Calculate total battery capacity.
    
    Args:
        capacity_ah: Battery capacity (Ah)
        voltage: Battery voltage (V)
        
    Returns:
        Total capacity (kWh)
    """
    return capacity_ah * voltage / 1000.0
