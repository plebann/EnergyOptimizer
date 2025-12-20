"""Tests for utility functions."""
import pytest

from custom_components.energy_optimizer.calculations.utils import (
    clamp,
    interpolate,
    is_valid_percentage,
    safe_float,
)


def test_safe_float():
    """Test safe float conversion."""
    # Normal conversion
    assert safe_float("123.45") == 123.45
    assert safe_float(123) == 123.0
    assert safe_float(123.45) == 123.45
    
    # None handling
    assert safe_float(None) == 0.0
    assert safe_float(None, 5.0) == 5.0
    
    # Invalid values
    assert safe_float("invalid") == 0.0
    assert safe_float("invalid", 10.0) == 10.0
    
    # Edge cases
    assert safe_float("") == 0.0
    assert safe_float([]) == 0.0


def test_clamp():
    """Test value clamping."""
    # Within range
    assert clamp(5, 0, 10) == 5
    
    # Below minimum
    assert clamp(-5, 0, 10) == 0
    
    # Above maximum
    assert clamp(15, 0, 10) == 10
    
    # At boundaries
    assert clamp(0, 0, 10) == 0
    assert clamp(10, 0, 10) == 10


def test_interpolate():
    """Test linear interpolation."""
    points = [(0, 0), (10, 100), (20, 150)]
    
    # Exact points
    assert interpolate(0, points) == 0
    assert interpolate(10, points) == 100
    assert interpolate(20, points) == 150
    
    # Between points
    assert interpolate(5, points) == 50
    assert interpolate(15, points) == 125
    
    # Outside range
    assert interpolate(-5, points) == 0  # Clamp to first
    assert interpolate(25, points) == 150  # Clamp to last
    
    # Empty points
    assert interpolate(5, []) == 0.0
    
    # Single point
    assert interpolate(5, [(10, 20)]) == 20


def test_is_valid_percentage():
    """Test percentage validation."""
    # Valid percentages
    assert is_valid_percentage(0) is True
    assert is_valid_percentage(50) is True
    assert is_valid_percentage(100) is True
    assert is_valid_percentage(0.5) is True
    assert is_valid_percentage(99.9) is True
    
    # Invalid percentages
    assert is_valid_percentage(-1) is False
    assert is_valid_percentage(101) is False
    assert is_valid_percentage(-50) is False
    assert is_valid_percentage(150) is False
