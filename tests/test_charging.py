"""Tests for charging calculations."""
import pytest

from custom_components.energy_optimizer.calculations.charging import (
    calculate_charge_current,
    calculate_charge_time,
    get_expected_current_multi_phase,
)


def test_get_expected_current_multi_phase():
    """Test multi-phase charging current calculation."""
    # Charging from 50% to 80% (mostly in Phase 1)
    # Should be close to 23A
    current = get_expected_current_multi_phase(2.88, 50, 200, 48)
    assert current == pytest.approx(23, rel=0.1)
    
    # Charging from 60% to 95% (spans Phase 1 and 2)
    # Should be between 9A and 23A
    current = get_expected_current_multi_phase(3.36, 60, 200, 48)
    assert 9 < current < 23
    
    # Charging from 92% to 98% (mostly in Phase 3)
    # Should be close to 4A
    current = get_expected_current_multi_phase(0.576, 92, 200, 48)
    assert current == pytest.approx(4, rel=0.3)
    
    # No charging needed
    assert get_expected_current_multi_phase(0, 50, 200, 48) == 0.0


def test_calculate_charge_time():
    """Test charge time calculation."""
    # 5 kWh at 23A, 48V, 95% efficiency
    # Power = 48V * 23A / 1000 = 1.104 kW
    # Required = 5 / 0.95 = 5.26 kWh
    # Time = 5.26 / 1.104 = ~4.76 hours
    time = calculate_charge_time(5, 23, 48, 95)
    assert time == pytest.approx(4.76, rel=0.01)
    
    # Zero current should return 0
    assert calculate_charge_time(5, 0, 48, 95) == 0.0
    
    # Zero efficiency should return 0
    assert calculate_charge_time(5, 23, 48, 0) == 0.0


def test_calculate_charge_current():
    """Test charge current calculation."""
    # Should use multi-phase logic
    current = calculate_charge_current(3.0, 50, 200, 48)
    assert current > 0
    
    # Zero energy should return valid current (but calculation will show 0)
    current = calculate_charge_current(0, 50, 200, 48)
    assert current >= 0
