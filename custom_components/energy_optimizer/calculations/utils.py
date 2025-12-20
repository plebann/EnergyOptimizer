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
