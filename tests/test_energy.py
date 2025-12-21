"""Tests for energy calculations."""
import pytest

from custom_components.energy_optimizer.calculations.energy import (
    calculate_energy_deficit,
    calculate_required_energy,
    calculate_required_energy_with_heat_pump,
    calculate_surplus_energy,
    calculate_target_soc_for_deficit,
    calculate_usage_ratio,
)


def test_calculate_required_energy():
    """Test required energy calculation."""
    # 2 kWh/h for 6 hours at 95% efficiency with 10% margin
    # Base = 2 * 6 = 12 kWh
    # With losses = 12 / 0.95 = 12.63 kWh
    # With margin = 12.63 * 1.1 = 13.89 kWh
    required = calculate_required_energy(2.0, 0, 6, 95, 1.1)
    assert required == pytest.approx(13.89, rel=0.01)
    
    # No margin (1.0 multiplier)
    required = calculate_required_energy(2.0, 0, 6, 95, 1.0)
    assert required == pytest.approx(12.63, rel=0.01)
    
    # Zero efficiency should return 0
    assert calculate_required_energy(2.0, 0, 6, 0) == 0.0

def test_calculate_usage_ratio():
    """Test usage ratio calculation."""
    # 24 kWh daily over 24 hours = 1 kWh/h
    assert calculate_usage_ratio(24, 24) == pytest.approx(1.0, rel=0.01)
    
    # 24 kWh daily over 12 hours = 1 kWh/h average
    assert calculate_usage_ratio(24, 12) == pytest.approx(1.0, rel=0.01)
    
    # Zero hours should return 0
    assert calculate_usage_ratio(24, 0) == 0.0


def test_calculate_surplus_energy():
    """Test surplus energy calculation."""
    # Reserve 10 kWh, required 5 kWh, PV 2 kWh
    # Surplus = (10 + 2) - 5 = 7 kWh
    surplus = calculate_surplus_energy(10, 5, 2)
    assert surplus == pytest.approx(7.0, rel=0.01)
    
    # No surplus case
    surplus = calculate_surplus_energy(5, 10, 0)
    assert surplus == 0.0
    
    # Negative surplus should return 0
    surplus = calculate_surplus_energy(3, 10, 2)
    assert surplus == 0.0


def test_calculate_energy_deficit():
    """Test energy deficit calculation."""
    # Space 8 kWh, required 12 kWh, PV 2 kWh
    # Net required = 12 - 2 = 10 kWh
    # Deficit = min(10, 8) = 8 kWh (limited by space)
    deficit = calculate_energy_deficit(8, 12, 2)
    assert deficit == pytest.approx(8.0, rel=0.01)
    
    # No deficit case (PV covers requirement)
    deficit = calculate_energy_deficit(8, 5, 10)
    assert deficit == 0.0
    
    # Deficit less than space
    deficit = calculate_energy_deficit(10, 5, 0)
    assert deficit == pytest.approx(5.0, rel=0.01)


def test_calculate_target_soc_for_deficit():
    """Test target SOC calculation for deficit."""
    # Current 50%, deficit 2.88 kWh, 200Ah 48V, max 100%
    # 2.88 kWh = 30% SOC
    # Target = 50 + 30 = 80%
    target = calculate_target_soc_for_deficit(50, 2.88, 200, 48, 100)
    assert target == pytest.approx(80, rel=0.01)
    
    # Should clamp to max SOC
    target = calculate_target_soc_for_deficit(50, 10, 200, 48, 95)
    assert target == 95
    
    # Zero deficit should return current SOC
    target = calculate_target_soc_for_deficit(50, 0, 200, 48, 100)
    assert target == 50


def test_calculate_required_energy_with_heat_pump():
    """Test required energy including heat pump."""
    # Base 2 kWh/h for 6 hours + 5 kWh heat pump
    # Base required = ~13.89 kWh (from previous test)
    # Total = 13.89 + 5 = 18.89 kWh
    total = calculate_required_energy_with_heat_pump(2.0, 6, 95, 5.0, 1.1)
    assert total == pytest.approx(18.89, rel=0.01)
    
    # No heat pump
    total = calculate_required_energy_with_heat_pump(2.0, 6, 95, 0, 1.1)
    assert total == pytest.approx(13.89, rel=0.01)
