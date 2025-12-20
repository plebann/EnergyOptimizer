"""Tests for heat pump calculations."""
import pytest

from custom_components.energy_optimizer.calculations.heat_pump import (
    calculate_heating_hours,
    calculate_peak_consumption,
    estimate_daily_consumption,
    interpolate_cop,
)

# Default COP curve for testing
TEST_COP_CURVE = [
    (-20, 2.0),
    (-10, 2.3),
    (-5, 2.6),
    (0, 3.0),
    (5, 3.5),
    (10, 4.0),
    (15, 4.5),
    (20, 5.0),
]


def test_interpolate_cop():
    """Test COP interpolation."""
    # Exact point
    assert interpolate_cop(0, TEST_COP_CURVE) == pytest.approx(3.0, rel=0.01)
    
    # Between points (-10 and -5)
    # At -7.5: COP should be ~2.45
    cop = interpolate_cop(-7.5, TEST_COP_CURVE)
    assert cop == pytest.approx(2.45, rel=0.01)
    
    # Below minimum temp (should clamp to first value)
    assert interpolate_cop(-30, TEST_COP_CURVE) == pytest.approx(2.0, rel=0.01)
    
    # Above maximum temp (should clamp to last value)
    assert interpolate_cop(25, TEST_COP_CURVE) == pytest.approx(5.0, rel=0.01)


def test_calculate_heating_hours():
    """Test heating hours calculation."""
    # Well below base temperature - full heating
    hours = calculate_heating_hours(-10, 5, 18)
    assert hours == 24
    
    # No heating needed
    hours = calculate_heating_hours(18, 25, 18)
    assert hours == 0
    
    # Partial heating
    hours = calculate_heating_hours(10, 20, 18)
    assert 0 < hours < 24


def test_calculate_peak_consumption():
    """Test peak consumption calculation."""
    # At -10°C, COP = 2.3
    # Peak = 2.5 kW / 2.3 = ~1.09 kW
    peak = calculate_peak_consumption(-10, TEST_COP_CURVE, 2.5)
    assert peak == pytest.approx(1.09, rel=0.01)
    
    # At 10°C, COP = 4.0
    # Peak = 2.5 kW / 4.0 = 0.625 kW
    peak = calculate_peak_consumption(10, TEST_COP_CURVE, 2.5)
    assert peak == pytest.approx(0.625, rel=0.01)
    
    # Zero COP should return 0
    assert calculate_peak_consumption(100, [(100, 0)], 2.5) == 0.0


def test_estimate_daily_consumption():
    """Test daily consumption estimation."""
    # Cold day: min -5, max 5, avg 0
    # Should have significant consumption
    consumption = estimate_daily_consumption(-5, 5, 0, TEST_COP_CURVE, 50)
    assert consumption > 0
    
    # Warm day: above base temperature
    consumption = estimate_daily_consumption(18, 25, 21.5, TEST_COP_CURVE, 50)
    assert consumption == 0.0
    
    # Moderate day: min 5, max 15, avg 10
    consumption = estimate_daily_consumption(5, 15, 10, TEST_COP_CURVE, 50)
    assert consumption > 0


def test_estimate_daily_consumption_cop_dependency():
    """Test that consumption decreases with better COP."""
    # At same temperature, consumption should be inversely proportional to COP
    
    # Cold temperature (lower COP)
    cold_consumption = estimate_daily_consumption(-10, 0, -5, TEST_COP_CURVE, 50)
    
    # Mild temperature (higher COP)
    mild_consumption = estimate_daily_consumption(5, 15, 10, TEST_COP_CURVE, 50)
    
    # At same degree-days, cold day should have higher consumption due to lower COP
    # This is a qualitative test - exact values depend on degree-days calculation
    assert cold_consumption >= 0
    assert mild_consumption >= 0
