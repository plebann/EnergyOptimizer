"""Calculation library for Energy Optimizer."""
from __future__ import annotations

from .battery import (
    calculate_battery_reserve,
    calculate_battery_space,
    calculate_total_capacity,
    calculate_usable_capacity,
    kwh_to_soc,
    soc_to_kwh,
)
from .charging import (
    calculate_charge_current,
    calculate_charge_time,
    get_expected_current_multi_phase,
)
from .energy import (
    calculate_energy_deficit,
    calculate_required_energy,
    calculate_required_energy_with_heat_pump,
    calculate_surplus_energy,
    calculate_target_soc_for_deficit,
    calculate_usage_ratio,
)
from .heat_pump import (
    calculate_heating_hours,
    calculate_peak_consumption,
    estimate_daily_consumption,
    interpolate_cop,
)
from .utils import clamp, interpolate, is_valid_percentage, safe_float

__all__ = [
    # Battery
    "calculate_battery_reserve",
    "calculate_battery_space",
    "calculate_total_capacity",
    "calculate_usable_capacity",
    "kwh_to_soc",
    "soc_to_kwh",
    # Charging
    "calculate_charge_current",
    "calculate_charge_time",
    "get_expected_current_multi_phase",
    # Energy
    "calculate_energy_deficit",
    "calculate_required_energy",
    "calculate_required_energy_with_heat_pump",
    "calculate_surplus_energy",
    "calculate_target_soc_for_deficit",
    "calculate_usage_ratio",
    # Heat pump
    "calculate_heating_hours",
    "calculate_peak_consumption",
    "estimate_daily_consumption",
    "interpolate_cop",
    # Utils
    "clamp",
    "interpolate",
    "is_valid_percentage",
    "safe_float",
]
