"""Tests for battery calculations."""
import pytest

from custom_components.energy_optimizer.calculations.battery import (
    calculate_battery_reserve,
    calculate_battery_space,
    calculate_total_capacity,
    calculate_usable_capacity,
    kwh_to_soc,
    soc_to_kwh,
)


def test_soc_to_kwh():
    """Test SOC to kWh conversion."""
    # 50% of 200Ah at 48V = 4.8 kWh
    assert soc_to_kwh(50, 200, 48) == pytest.approx(4.8, rel=0.01)
    
    # 100% of 200Ah at 48V = 9.6 kWh
    assert soc_to_kwh(100, 200, 48) == pytest.approx(9.6, rel=0.01)
    
    # 0% should be 0
    assert soc_to_kwh(0, 200, 48) == 0.0


def test_kwh_to_soc():
    """Test kWh to SOC conversion."""
    # 4.8 kWh with 200Ah 48V battery = 50%
    assert kwh_to_soc(4.8, 200, 48) == pytest.approx(50, rel=0.01)
    
    # 9.6 kWh = 100%
    assert kwh_to_soc(9.6, 200, 48) == pytest.approx(100, rel=0.01)
    
    # 0 kWh = 0%
    assert kwh_to_soc(0, 200, 48) == 0.0
    
    # Handle zero capacity gracefully
    assert kwh_to_soc(5, 0, 48) == 0.0


def test_calculate_battery_reserve():
    """Test battery reserve calculation."""
    # Current 70%, min 10%, 200Ah 48V
    # Reserve = (70-10)% * 200 * 48 / 1000 = 5.76 kWh
    reserve = calculate_battery_reserve(70, 10, 200, 48)
    assert reserve == pytest.approx(5.76, rel=0.01)
    
    # At minimum SOC, reserve should be 0
    assert calculate_battery_reserve(10, 10, 200, 48) == 0.0
    
    # Below minimum, reserve should be 0
    assert calculate_battery_reserve(5, 10, 200, 48) == 0.0


def test_calculate_battery_space():
    """Test battery space calculation."""
    # Current 70%, max 100%, 200Ah 48V
    # Space = (100-70)% * 200 * 48 / 1000 = 2.88 kWh
    space = calculate_battery_space(70, 100, 200, 48)
    assert space == pytest.approx(2.88, rel=0.01)
    
    # At maximum SOC, space should be 0
    assert calculate_battery_space(100, 100, 200, 48) == 0.0
    
    # Above maximum, space should be 0
    assert calculate_battery_space(105, 100, 200, 48) == 0.0


def test_calculate_usable_capacity():
    """Test usable capacity calculation."""
    # Between 10% and 100%, 200Ah 48V
    # Usable = 90% * 200 * 48 / 1000 = 8.64 kWh
    usable = calculate_usable_capacity(200, 48, 10, 100)
    assert usable == pytest.approx(8.64, rel=0.01)
    
    # Restricted range 20-80%
    # Usable = 60% * 200 * 48 / 1000 = 5.76 kWh
    usable = calculate_usable_capacity(200, 48, 20, 80)
    assert usable == pytest.approx(5.76, rel=0.01)


def test_calculate_total_capacity():
    """Test total capacity calculation."""
    # 200Ah * 48V / 1000 = 9.6 kWh
    assert calculate_total_capacity(200, 48) == pytest.approx(9.6, rel=0.01)
    
    # 100Ah * 24V / 1000 = 2.4 kWh
    assert calculate_total_capacity(100, 24) == pytest.approx(2.4, rel=0.01)
