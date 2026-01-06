"""Tests for charging calculations."""
import pytest

from custom_components.energy_optimizer.calculations.charging import (
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

