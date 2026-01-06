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
from .energy import (
    calculate_required_energy,
    calculate_surplus_energy,
)
from .heat_pump import (
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
    # Energy
    "calculate_required_energy",
    "calculate_surplus_energy",
    # Heat pump
    "estimate_daily_consumption",
    "interpolate_cop",
    # Utils
    "clamp",
    "interpolate",
    "is_valid_percentage",
    "safe_float",
]
