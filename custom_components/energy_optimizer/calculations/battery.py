"""Battery calculations for Energy Optimizer."""
from __future__ import annotations

from math import ceil


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
    current_soc: float,
    min_soc: float,
    capacity_ah: float,
    voltage: float,
    efficiency: float = 100.0,
) -> float:
    """Calculate available battery reserve above minimum SOC.

    Args:
        current_soc: Current state of charge (%).
        min_soc: Minimum allowed SOC (%).
        capacity_ah: Battery capacity (Ah).
        voltage: Battery voltage (V).
        efficiency: Discharge efficiency (%).

    Returns:
        Available reserve energy (kWh).
    """
    if current_soc <= min_soc:
        return 0.0

    if efficiency <= 0:
        return 0.0

    reserve_soc = current_soc - min_soc
    reserve_kwh = soc_to_kwh(reserve_soc, capacity_ah, voltage)
    return reserve_kwh * (efficiency / 100.0)


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


def calculate_expected_charge_current(
    energy_to_charge_kwh: float,
    current_soc: float,
    capacity_ah: float,
    voltage: float,
    *,
    target_charge_time_hours: float = 2.0,
    lvl1_current: float = 23.0,
    lvl2_threshold: float = 50.0,
    lvl2_current: float = 18.0,
    lvl3_threshold: float = 70.0,
    lvl3_current: float = 9.0,
    lvl4_threshold: float = 90.0,
    lvl4_current: float = 5.0,
) -> int:
    """Calculate expected charge current based on SOC phases and time window.

    Mirrors the legacy get_expected_current macro logic.
    """
    if energy_to_charge_kwh <= 0 or capacity_ah <= 0 or voltage <= 0:
        return 0

    capacity_kwh = (capacity_ah * voltage) / 1000.0
    if capacity_kwh <= 0:
        return 0

    target_soc = current_soc + (energy_to_charge_kwh / capacity_kwh * 100.0)
    target_soc = min(target_soc, 100.0)

    def energy_in_range(soc_start: float, soc_end: float) -> float:
        if soc_end <= soc_start:
            return 0.0
        return (soc_end - soc_start) / 100.0 * capacity_kwh

    phase1_energy = 0.0
    if current_soc < lvl2_threshold:
        phase1_start = current_soc
        phase1_end = min(target_soc, lvl2_threshold)
        phase1_energy = energy_in_range(phase1_start, phase1_end)

    phase2_energy = 0.0
    if current_soc < lvl3_threshold and target_soc > lvl2_threshold:
        phase2_start = max(current_soc, lvl2_threshold)
        phase2_end = min(target_soc, lvl3_threshold)
        phase2_energy = energy_in_range(phase2_start, phase2_end)

    phase3_energy = 0.0
    if target_soc > lvl3_threshold:
        phase3_start = max(current_soc, lvl3_threshold)
        phase3_end = target_soc
        phase3_energy = energy_in_range(phase3_start, phase3_end)

    phase4_energy = 0.0
    if target_soc > lvl4_threshold:
        phase4_start = max(current_soc, lvl4_threshold)
        phase4_end = target_soc
        phase4_energy = energy_in_range(phase4_start, phase4_end)

    phase1_time = (
        (phase1_energy * 1000.0) / (voltage * lvl1_current)
        if phase1_energy > 0
        else 0.0
    )
    phase2_time = (
        (phase2_energy * 1000.0) / (voltage * lvl2_current)
        if phase2_energy > 0
        else 0.0
    )
    phase3_time = (
        (phase3_energy * 1000.0) / (voltage * lvl3_current)
        if phase3_energy > 0
        else 0.0
    )
    phase4_time = (
        (phase4_energy * 1000.0) / (voltage * lvl4_current)
        if phase4_energy > 0
        else 0.0
    )

    total_time_at_max = phase1_time + phase2_time + phase3_time + phase4_time

    if total_time_at_max <= target_charge_time_hours:
        required_power_w = (energy_to_charge_kwh * 1000.0) / target_charge_time_hours
        average_current = required_power_w / voltage

        if current_soc < lvl2_threshold:
            recommended_current = min(average_current, lvl1_current)
        elif current_soc < lvl3_threshold:
            recommended_current = min(average_current, lvl2_current)
        elif current_soc < lvl4_threshold:
            recommended_current = min(average_current, lvl3_current)
        else:
            recommended_current = min(average_current, lvl4_current)
    else:
        recommended_current = lvl1_current

    return int(ceil(recommended_current))


def calculate_soc_delta(
    energy_to_charge_kwh: float,
    *,
    capacity_ah: float,
    voltage: float,
) -> float:
    """Calculate SOC delta for a given energy amount."""
    return kwh_to_soc(energy_to_charge_kwh, capacity_ah, voltage)


def calculate_target_soc(
    current_soc: float,
    soc_delta: float,
    *,
    max_soc: float,
) -> float:
    """Calculate target SOC rounded up to full percent."""
    target_soc = min(current_soc + soc_delta, max_soc)
    return float(ceil(target_soc))


def calculate_charge_current(
    energy_to_charge_kwh: float,
    *,
    current_soc: float,
    capacity_ah: float,
    voltage: float,
) -> int:
    """Calculate charge current for a given energy amount."""
    return calculate_expected_charge_current(
        energy_to_charge_kwh,
        current_soc,
        capacity_ah,
        voltage,
    )


def calculate_total_capacity(capacity_ah: float, voltage: float) -> float:
    """Calculate total battery capacity.
    
    Args:
        capacity_ah: Battery capacity (Ah)
        voltage: Battery voltage (V)
        
    Returns:
        Total capacity (kWh)
    """
    return capacity_ah * voltage / 1000.0
