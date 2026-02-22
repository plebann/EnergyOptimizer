"""Tests for energy calculations."""
import pytest

from custom_components.energy_optimizer.calculations.energy import (
    calculate_needed_reserve,
    calculate_needed_reserve_sufficiency,
    calculate_required_energy,
    calculate_surplus_energy,
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


def test_calculate_needed_reserve():
    """Test demand-first needed reserve calculation."""
    assert calculate_needed_reserve(10.0, 3.0) == pytest.approx(7.0, rel=0.01)
    assert calculate_needed_reserve(5.0, 10.0) == 0.0


def test_calculate_needed_reserve_sufficiency():
    """Test needed reserve calculation for sufficiency window."""
    assert calculate_needed_reserve_sufficiency(8.0, 2.5) == pytest.approx(5.5, rel=0.01)
    assert calculate_needed_reserve_sufficiency(3.0, 4.0) == 0.0
