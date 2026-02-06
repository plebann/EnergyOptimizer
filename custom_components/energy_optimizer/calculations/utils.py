"""Calculation utilities for Energy Optimizer."""
from __future__ import annotations

from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float with None handling.
    
    Args:
        value: Value to convert
        default: Default value if conversion fails
        
    Returns:
        Float value or default
    """
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value between minimum and maximum.
    
    Args:
        value: Value to clamp
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        
    Returns:
        Clamped value
    """
    return max(min_val, min(value, max_val))


def interpolate(x: float, points: list[tuple[float, float]]) -> float:
    """Linear interpolation from list of (x, y) points.
    
    Args:
        x: X value to interpolate
        points: List of (x, y) tuples, must be sorted by x
        
    Returns:
        Interpolated y value
    """
    if not points:
        return 0.0
    
    # Handle out of bounds
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    
    # Find surrounding points
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        
        if x1 <= x <= x2:
            # Linear interpolation
            if x2 == x1:
                return y1
            return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    
    return points[-1][1]


def is_valid_percentage(value: float) -> bool:
    """Validate value is in 0-100 range.
    
    Args:
        value: Value to validate
        
    Returns:
        True if value is valid percentage
    """
    return 0 <= value <= 100

def build_hourly_usage_array(
    config: dict[str, Any],
    hass_states_get: Any,
    daily_load_fallback: float | None = None,
) -> list[float]:
    """Build 24-element array of hourly usage from time-windowed sensors.
    
    Creates array where each hour (0-23) has the average usage rate from
    its corresponding time window sensor. Falls back to daily average if
    time-windowed sensors not configured.
    
    Args:
        config: Integration config dictionary
        hass_states_get: Function to get entity state (hass.states.get)
        daily_load_fallback: Daily load to use as fallback (kWh)
        
    Returns:
        List of 24 floats representing usage per hour (kWh/h)
        
    Example:
        >>> array = build_hourly_usage_array(config, hass.states.get, 48.0)
        >>> array[0]  # Hour 0 (00:00-01:00)
        0.8  # From CONF_LOAD_USAGE_00_04 sensor
        >>> array[18]  # Hour 18 (18:00-19:00)
        2.8  # From CONF_LOAD_USAGE_16_20 sensor
    """
    import logging
    from ..const import (
        CONF_DAILY_LOAD_SENSOR,
        CONF_LOAD_USAGE_00_04,
        CONF_LOAD_USAGE_04_08,
        CONF_LOAD_USAGE_08_12,
        CONF_LOAD_USAGE_12_16,
        CONF_LOAD_USAGE_16_20,
        CONF_LOAD_USAGE_20_24,
    )
    
    _LOGGER = logging.getLogger(__name__)
    
    # Define time window mapping
    windows = [
        (0, 4, CONF_LOAD_USAGE_00_04),
        (4, 8, CONF_LOAD_USAGE_04_08),
        (8, 12, CONF_LOAD_USAGE_08_12),
        (12, 16, CONF_LOAD_USAGE_12_16),
        (16, 20, CONF_LOAD_USAGE_16_20),
        (20, 24, CONF_LOAD_USAGE_20_24),
    ]
    
    # Determine fallback value
    if daily_load_fallback is None:
        daily_sensor = config.get(CONF_DAILY_LOAD_SENSOR)
        if daily_sensor:
            state = hass_states_get(daily_sensor)
            if state and state.state not in (None, "unknown", "unavailable"):
                try:
                    daily_load_fallback = float(state.state)
                except (ValueError, TypeError):
                    daily_load_fallback = 48.0
            else:
                daily_load_fallback = 48.0
        else:
            daily_load_fallback = 48.0
    
    fallback_hourly = daily_load_fallback / 24.0
    
    # Build 24-hour array
    hourly_array = []
    any_window_configured = False
    
    for start_hour, end_hour, conf_key in windows:
        sensor_entity = config.get(conf_key)
        
        if sensor_entity:
            state = hass_states_get(sensor_entity)
            if state and state.state not in (None, "unknown", "unavailable"):
                try:
                    window_avg = float(state.state)
                    any_window_configured = True
                except (ValueError, TypeError):
                    window_avg = fallback_hourly
            else:
                window_avg = fallback_hourly
        else:
            window_avg = fallback_hourly
        
        # Extend array with this window's average for each hour
        hourly_array.extend([window_avg] * (end_hour - start_hour))
    
    # Log if falling back to uniform distribution
    if not any_window_configured:
        _LOGGER.debug(
            "No time-windowed load sensors configured, using uniform distribution: %.2f kWh/h",
            fallback_hourly
        )
    
    return hourly_array