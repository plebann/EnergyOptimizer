"""Tests for utility functions."""

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


# ===== Time-Windowed Calculation Tests =====


from custom_components.energy_optimizer.calculations.utils import (
    build_hourly_usage_array,
    calculate_dynamic_usage_ratio,
)
import pytest


@pytest.mark.unit
def test_build_hourly_usage_array_all_sensors():
    """Test building hourly array with all sensors configured."""
    config = {
        "load_usage_00_04": "sensor.usage_00_04",
        "load_usage_04_08": "sensor.usage_04_08",
        "load_usage_08_12": "sensor.usage_08_12",
        "load_usage_12_16": "sensor.usage_12_16",
        "load_usage_16_20": "sensor.usage_16_20",
        "load_usage_20_24": "sensor.usage_20_24",
    }
    
    # Mock state values: 1.0, 1.5, 2.0, 2.5, 3.0, 2.0 kWh/h
    def mock_get_state(entity_id):
        values = {
            "sensor.usage_00_04": "1.0",
            "sensor.usage_04_08": "1.5",
            "sensor.usage_08_12": "2.0",
            "sensor.usage_12_16": "2.5",
            "sensor.usage_16_20": "3.0",
            "sensor.usage_20_24": "2.0",
        }
        
        class MockState:
            def __init__(self, state_value):
                self.state = state_value
        
        return MockState(values.get(entity_id, "0"))
    
    result = build_hourly_usage_array(config, mock_get_state)
    
    # Check length
    assert len(result) == 24
    
    # Check values for each window
    assert all(result[i] == 1.0 for i in range(0, 4))  # 00-04
    assert all(result[i] == 1.5 for i in range(4, 8))  # 04-08
    assert all(result[i] == 2.0 for i in range(8, 12))  # 08-12
    assert all(result[i] == 2.5 for i in range(12, 16))  # 12-16
    assert all(result[i] == 3.0 for i in range(16, 20))  # 16-20
    assert all(result[i] == 2.0 for i in range(20, 24))  # 20-24


@pytest.mark.unit
def test_build_hourly_usage_array_partial_sensors():
    """Test building hourly array with only some sensors configured."""
    config = {
        "load_usage_00_04": "sensor.usage_00_04",
        "load_usage_08_12": "sensor.usage_08_12",
        "daily_load_sensor": "sensor.daily_load",
    }
    
    def mock_get_state(entity_id):
        values = {
            "sensor.usage_00_04": "1.0",
            "sensor.usage_08_12": "2.0",
            "sensor.daily_load": "48.0",  # 48 kWh/day = 2.0 kWh/h
        }
        
        class MockState:
            def __init__(self, state_value):
                self.state = state_value
        
        return MockState(values.get(entity_id, "0"))
    
    result = build_hourly_usage_array(config, mock_get_state)
    
    # Check that configured windows have correct values
    assert all(result[i] == 1.0 for i in range(0, 4))
    assert all(result[i] == 2.0 for i in range(8, 12))
    
    # Check that other hours use daily average (48/24 = 2.0)
    assert all(result[i] == 2.0 for i in range(4, 8))
    assert all(result[i] == 2.0 for i in range(12, 16))


@pytest.mark.unit
def test_build_hourly_usage_array_no_sensors():
    """Test building hourly array with no time-windowed sensors."""
    config = {
        "daily_load_sensor": "sensor.daily_load",
    }
    
    def mock_get_state(entity_id):
        class MockState:
            def __init__(self, state_value):
                self.state = state_value
        
        return MockState("60.0")  # 60 kWh/day = 2.5 kWh/h
    
    result = build_hourly_usage_array(config, mock_get_state)
    
    # All hours should be 2.5
    assert len(result) == 24
    assert all(value == 2.5 for value in result)

@pytest.mark.unit

def test_build_hourly_usage_array_invalid_state():
    """Test handling of invalid sensor states."""
    config = {
        "load_usage_00_04": "sensor.usage_00_04",
        "daily_load_sensor": "sensor.daily_load",
    }
    
    def mock_get_state(entity_id):
        values = {
            "sensor.usage_00_04": "invalid",
            "sensor.daily_load": "48.0",
        }
        
        class MockState:
            def __init__(self, state_value):
                self.state = state_value
        
        return MockState(values.get(entity_id, "0"))
    
    result = build_hourly_usage_array(config, mock_get_state)
    
    # Should fall back to daily average for invalid window
    assert all(result[i] == 2.0 for i in range(0, 4))

@pytest.mark.unit

def test_calculate_dynamic_usage_ratio_normal():
    """Test dynamic usage ratio calculation with normal consumption."""
    config = {
        "today_load_sensor": "sensor.today_load",
        "daily_load_sensor": "sensor.daily_load",
    }
    
    def mock_get_state(entity_id):
        values = {
            "sensor.today_load": "24.0",  # 24 kWh so far
            "sensor.daily_load": "48.0",  # 48 kWh average per day
        }
        
        class MockState:
            def __init__(self, state_value):
                self.state = state_value
        
        return MockState(values.get(entity_id, "0"))
    
    # At 14:00 (2 PM), 24 kWh consumed
    # Ratio = (24 / 14) / (48 / 24) = 1.714 / 2.0 = 0.857
    # Should return 1.0 (minimum)
    result = calculate_dynamic_usage_ratio(config, mock_get_state, 14, 0)
    assert result == 1.0
@pytest.mark.unit


def test_calculate_dynamic_usage_ratio_high_consumption():
    """Test dynamic usage ratio with higher than average consumption."""
    config = {
        "today_load_sensor": "sensor.today_load",
        "daily_load_sensor": "sensor.daily_load",
    }
    
    def mock_get_state(entity_id):
        values = {
            "sensor.today_load": "36.0",  # 36 kWh so far (high)
            "sensor.daily_load": "48.0",  # 48 kWh average per day
        }
        
        class MockState:
            def __init__(self, state_value):
                self.state = state_value
        
        return MockState(values.get(entity_id, "0"))
    
    # At 14:00 (2 PM), 36 kWh consumed
    # Ratio = (36 / 14) / (48 / 24) = 2.571 / 2.0 = 1.286
    result = calculate_dynamic_usage_ratio(config, mock_get_state, 14, 0)
    assert result > 1.2  # Approximate check
@pytest.mark.unit


def test_calculate_dynamic_usage_ratio_early_morning():
    """Test dynamic usage ratio in early morning hours."""
    config = {
        "today_load_sensor": "sensor.today_load",
        "daily_load_sensor": "sensor.daily_load",
    }
    
    def mock_get_state(entity_id):
        values = {
            "sensor.today_load": "2.0",
            "sensor.daily_load": "48.0",
        }
        
        class MockState:
            def __init__(self, state_value):
                self.state = state_value
        
        return MockState(values.get(entity_id, "0"))
    
    # At 02:00 (2 AM), ratio should be 1.0 (too early to judge)
    result = calculate_dynamic_usage_ratio(config, mock_get_state, 2, 0)
@pytest.mark.unit
    assert result == 1.0


def test_calculate_dynamic_usage_ratio_missing_sensors():
    """Test dynamic usage ratio with missing sensors."""
    config = {}
    
    def mock_get_state(entity_id):
        return None
    
@pytest.mark.unit
    result = calculate_dynamic_usage_ratio(config, mock_get_state, 14, 0)
    assert result == 1.0


def test_calculate_dynamic_usage_ratio_with_heat_pump():
    """Test dynamic usage ratio with separate heat pump consumption."""
    config = {
        "today_load_sensor": "sensor.today_load",
        "daily_load_sensor": "sensor.daily_load",
        "today_heat_pump_sensor": "sensor.today_heat_pump",
    }
    
    def mock_get_state(entity_id):
        values = {
            "sensor.today_load": "30.0",  # 30 kWh total
            "sensor.daily_load": "48.0",  # 48 kWh average
            "sensor.today_heat_pump": "6.0",  # 6 kWh heat pump
        }
        
        class MockState:
            def __init__(self, state_value):
                self.state = state_value
        
        return MockState(values.get(entity_id, "0"))
    
    # At 12:00 (noon), effective = 30 - 6 = 24 kWh
    # Ratio = (24 / 12) / (48 / 24) = 2.0 / 2.0 = 1.0
    result = calculate_dynamic_usage_ratio(config, mock_get_state, 12, 0)
    assert result == 1.0
