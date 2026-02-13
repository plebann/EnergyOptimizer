"""Time window helpers for hour-based ranges."""
from __future__ import annotations


def build_hour_window(start_hour: int, end_hour: int) -> list[int]:
    """Return ordered hours for a window; supports midnight wrap."""
    if end_hour < start_hour:
        return list(range(start_hour, 24)) + list(range(0, end_hour))
    return list(range(start_hour, end_hour))


def is_hour_in_window(hour: int, start_hour: int, end_hour: int) -> bool:
    """Return True when hour is inside the window; supports midnight wrap."""
    if end_hour < start_hour:
        return hour >= start_hour or hour < end_hour
    return start_hour <= hour < end_hour
