"""Calculation library for Energy Optimizer."""
from __future__ import annotations

from .price_windows import (
    MiddaySellWindowResult,
    QuarterHourPricePoint,
    build_midday_sell_window_result,
    expand_hourly_sell_prices,
    find_cheapest_midday_sell_window,
    format_sell_window,
    select_midday_window,
)
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
from .utils import clamp, interpolate, is_valid_percentage, safe_float

__all__ = [
    # Price windows
    "build_midday_sell_window_result",
    "expand_hourly_sell_prices",
    "find_cheapest_midday_sell_window",
    "format_sell_window",
    "MiddaySellWindowResult",
    "QuarterHourPricePoint",
    "select_midday_window",
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
    # Utils
    "clamp",
    "interpolate",
    "is_valid_percentage",
    "safe_float",
]
