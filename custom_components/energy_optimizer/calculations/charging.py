"""Charging calculations for Energy Optimizer."""
from __future__ import annotations

from .battery import kwh_to_soc, soc_to_kwh


def calculate_charge_current(
    energy_kwh: float, current_soc: float, capacity_ah: float, voltage: float
) -> float:
    """Calculate required charge current for target energy.
    
    Args:
        energy_kwh: Energy to charge (kWh)
        current_soc: Current state of charge (%)
        capacity_ah: Battery capacity (Ah)
        voltage: Battery voltage (V)
        
    Returns:
        Required charge current (A)
    """
    if voltage == 0:
        return 0.0
    
    # Use multi-phase logic
    return get_expected_current_multi_phase(energy_kwh, current_soc, capacity_ah, voltage)


def calculate_charge_time(
    energy_kwh: float, current_a: float, voltage: float, efficiency: float
) -> float:
    """Calculate estimated charge time.
    
    Args:
        energy_kwh: Energy to charge (kWh)
        current_a: Charge current (A)
        voltage: Battery voltage (V)
        efficiency: Charge efficiency (%)
        
    Returns:
        Charge time (hours)
    """
    if current_a == 0 or efficiency == 0:
        return 0.0
    
    # Account for efficiency losses
    required_energy = energy_kwh / (efficiency / 100.0)
    
    # Time = Energy / Power, where Power = Voltage * Current
    power_kw = voltage * current_a / 1000.0
    if power_kw == 0:
        return 0.0
    
    return required_energy / power_kw


def get_expected_current_multi_phase(
    energy_to_charge: float, current_soc: float, capacity_ah: float, voltage: float
) -> float:
    """Calculate expected charge current considering multi-phase charging.
    
    Battery charging has different phases with different currents:
    - Phase 1 (0-70% SOC): 23A charging current
    - Phase 2 (70-90% SOC): 9A charging current  
    - Phase 3 (90-100% SOC): 4A charging current
    
    Args:
        energy_to_charge: Energy to charge (kWh)
        current_soc: Current state of charge (%)
        capacity_ah: Battery capacity (Ah)
        voltage: Battery voltage (V)
        
    Returns:
        Weighted average charge current (A)
    """
    # Define charging phases (SOC threshold, current)
    phases = [
        (0, 70, 23),   # Phase 1: 0-70% at 23A
        (70, 90, 9),   # Phase 2: 70-90% at 9A
        (90, 100, 4),  # Phase 3: 90-100% at 4A
    ]
    
    # Calculate target SOC
    target_soc = current_soc + kwh_to_soc(energy_to_charge, capacity_ah, voltage)
    target_soc = min(target_soc, 100)
    
    if target_soc <= current_soc:
        return 0.0
    
    # Calculate weighted average current across phases
    total_energy = 0.0
    weighted_current = 0.0
    
    for phase_start, phase_end, phase_current in phases:
        # Skip phases before current SOC
        if phase_end <= current_soc:
            continue
        
        # Skip phases after target SOC
        if phase_start >= target_soc:
            continue
        
        # Calculate SOC range in this phase
        phase_soc_start = max(phase_start, current_soc)
        phase_soc_end = min(phase_end, target_soc)
        phase_soc_delta = phase_soc_end - phase_soc_start
        
        if phase_soc_delta <= 0:
            continue
        
        # Calculate energy in this phase
        phase_energy = soc_to_kwh(phase_soc_delta, capacity_ah, voltage)
        
        # Weight current by energy proportion
        total_energy += phase_energy
        weighted_current += phase_current * phase_energy
    
    if total_energy == 0:
        return 23  # Default to Phase 1 current
    
    return weighted_current / total_energy
