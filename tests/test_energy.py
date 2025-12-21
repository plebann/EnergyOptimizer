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


# ===== Time-Windowed Calculation Tests =====


from custom_components.energy_optimizer.calculations.energy import (
    calculate_required_energy_windowed,
)


@pytest.mark.unit
def test_calculate_required_energy_windowed_basic():
    """Test windowed calculation with basic usage pattern."""
    config = {
        "load_usage_00_04": "sensor.usage_00_04",
        "load_usage_04_08": "sensor.usage_04_08",
        "load_usage_08_12": "sensor.usage_08_12",
        "load_usage_12_16": "sensor.usage_12_16",
        "load_usage_16_20": "sensor.usage_16_20",
        "load_usage_20_24": "sensor.usage_20_24",
        "daily_load_sensor": "sensor.daily_load",
        "today_load_sensor": "sensor.today_load",
    }
    
    def mock_get_state(entity_id):
        values = {
            "sensor.usage_00_04": "1.0",
            "sensor.usage_04_08": "1.5",
            "sensor.usage_08_12": "2.0",
            "sensor.usage_12_16": "2.5",
            "sensor.usage_16_20": "3.0",
            "sensor.usage_20_24": "2.0",
            "sensor.daily_load": "48.0",
            "sensor.today_load": "24.0",  # Normal consumption
        }
        
        class MockState:
            def __init__(self, state_value):
                self.state = state_value
        
        return MockState(values.get(entity_id, "0"))
    
    # From 8:00 to 16:00 (8 hours), at 14:00
    # Hours 8-12: 2.0 kWh/h × 4 = 8.0 kWh
    # Hours 12-16: 2.5 kWh/h × 4 = 10.0 kWh
    # Total base = 18.0 kWh
    # Dynamic ratio at 14:00 = max(1.0, (24/14)/(48/24)) = max(1.0, 0.857) = 1.0
    # Adjusted = 18.0 × 1.0 = 18.0 kWh
    result = calculate_required_energy_windowed(
        start_hour=8,
        end_hour=16,
        config=config,
        hass_states_get=mock_get_state,
        efficiency=95,
        current_hour=14,
        current_minute=0,
    )
    
    # With 95% efficiency: 18.0 / 0.95 ≈ 18.95 kWh
    assert result == pytest.approx(18.95, rel=0.05)


@pytest.mark.unit
def test_calculate_required_energy_windowed_high_consumption():
    """Test windowed calculation with high consumption day."""
    config = {
        "load_usage_08_12": "sensor.usage_08_12",
        "load_usage_12_16": "sensor.usage_12_16",
        "daily_load_sensor": "sensor.daily_load",
        "today_load_sensor": "sensor.today_load",
    }
    
    def mock_get_state(entity_id):
        values = {
            "sensor.usage_08_12": "2.0",
            "sensor.usage_12_16": "2.5",
            "sensor.daily_load": "48.0",
            "sensor.today_load": "36.0",  # High consumption (1.5x expected)
        }
        
        class MockState:
            def __init__(self, state_value):
                self.state = state_value
        
        return MockState(values.get(entity_id, "0"))
    
    # At 14:00, dynamic ratio = max(1.0, (36/14)/(48/24)) = max(1.0, 1.286) = 1.286
    # This should increase the energy requirement proportionally
    result = calculate_required_energy_windowed(
        start_hour=8,
        end_hour=16,
        config=config,
        hass_states_get=mock_get_state,
        efficiency=95,
        current_hour=14,
        current_minute=0,
    )
    
    # Should be higher than basic case
    assert result > 18.0


@pytest.mark.unit
def test_calculate_required_energy_windowed_cross_midnight():
    """Test windowed calculation spanning midnight."""
    config = {
        "load_usage_20_24": "sensor.usage_20_24",
        "load_usage_00_04": "sensor.usage_00_04",
        "load_usage_04_08": "sensor.usage_04_08",
        "daily_load_sensor": "sensor.daily_load",
        "today_load_sensor": "sensor.today_load",
    }
    
    def mock_get_state(entity_id):
        values = {
            "sensor.usage_20_24": "2.0",
            "sensor.usage_00_04": "1.0",
            "sensor.usage_04_08": "1.5",
            "sensor.daily_load": "48.0",
            "sensor.today_load": "40.0",
        }
        
        class MockState:
            def __init__(self, state_value):
                self.state = state_value
        
        return MockState(values.get(entity_id, "0"))
    
    # From 22:00 to 06:00 (8 hours)
    # Hours 22-24: 2.0 kWh/h × 2 = 4.0 kWh
    # Hours 0-4: 1.0 kWh/h × 4 = 4.0 kWh
    # Hours 4-6: 1.5 kWh/h × 2 = 3.0 kWh
    # Total = 11.0 kWh
    result = calculate_required_energy_windowed(
        start_hour=22,
        end_hour=6,
        config=config,
        hass_states_get=mock_get_state,
        efficiency=95,
        include_tomorrow=True,
        current_hour=20,
        current_minute=0,
    )
    
    assert result > 10.0  # Should account for base usage


@pytest.mark.unit
def test_calculate_required_energy_windowed_with_losses():
    """Test windowed calculation with hourly losses."""
    config = {
        "load_usage_08_12": "sensor.usage_08_12",
        "daily_load_sensor": "sensor.daily_load",
        "today_load_sensor": "sensor.today_load",
    }
    
    def mock_get_state(entity_id):
        values = {
            "sensor.usage_08_12": "2.0",
            "sensor.daily_load": "48.0",
            "sensor.today_load": "24.0",
        }
        
        class MockState:
            def __init__(self, state_value):
                self.state = state_value
        
        return MockState(values.get(entity_id, "0"))
    
    # 4 hours with 0.1 kWh/h losses
    result = calculate_required_energy_windowed(
        start_hour=8,
        end_hour=12,
        config=config,
        hass_states_get=mock_get_state,
        efficiency=95,
        hourly_losses=0.1,
        current_hour=10,
        current_minute=0,
    )
    
    # Base = 2.0 × 4 = 8.0 kWh
    # With efficiency = 8.0 / 0.95 ≈ 8.42 kWh
    # Losses = 0.1 × 4 / 0.95 ≈ 0.42 kWh
    # Total ≈ 8.84 kWh
    assert result == pytest.approx(8.84, rel=0.05)


@pytest.mark.unit
def test_calculate_required_energy_windowed_fallback():
    """Test fallback when time-windowed sensors not available."""
    config = {
        "daily_load_sensor": "sensor.daily_load",
        "today_load_sensor": "sensor.today_load",
    }
    
    def mock_get_state(entity_id):
        values = {
            "sensor.daily_load": "48.0",
            "sensor.today_load": "24.0",
        }
        
        class MockState:
            def __init__(self, state_value):
                self.state = state_value
        
        return MockState(values.get(entity_id, "0"))
    
    # Should fall back to daily average (48/24 = 2.0 kWh/h)
    result = calculate_required_energy_windowed(
        start_hour=8,
        end_hour=16,
        config=config,
        hass_states_get=mock_get_state,
        efficiency=95,
        current_hour=12,
        current_minute=0,
    )
    
    # 8 hours × 2.0 kWh/h / 0.95 ≈ 16.84 kWh
    assert result == pytest.approx(16.84, rel=0.05)

