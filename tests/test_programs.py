"""Tests for time-based program selection logic."""
import pytest
from datetime import datetime, time
from unittest.mock import Mock, MagicMock

# Import the function to test
import sys
sys.path.insert(0, '../custom_components/energy_optimizer')
from custom_components.energy_optimizer import get_active_program_entity
from custom_components.energy_optimizer.const import (
    CONF_PROG1_SOC_ENTITY, CONF_PROG1_TIME_START,
    CONF_PROG2_SOC_ENTITY, CONF_PROG2_TIME_START,
    CONF_PROG3_SOC_ENTITY, CONF_PROG3_TIME_START,
)


def create_mock_hass(entity_states=None):
    """Create a mock Home Assistant instance with entity states."""
    hass = Mock()
    states = {}
    
    if entity_states:
        for entity_id, state_value in entity_states.items():
            state_obj = Mock()
            state_obj.state = state_value
            states[entity_id] = state_obj
    
    hass.states.get = lambda entity_id: states.get(entity_id)
    return hass


def test_no_programs_configured():
    """Test when no programs are configured."""
    hass = create_mock_hass()
    config = {}
    current_time = datetime(2025, 12, 20, 10, 0)
    
    result = get_active_program_entity(hass, config, current_time)
    assert result is None


def test_single_program_time_match():
    """Test matching a single configured program."""
    hass = create_mock_hass({
        "input_datetime.prog1_start": "06:00"
    })
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG1_TIME_START: "input_datetime.prog1_start",
    }
    
    # Test time within window
    current_time = datetime(2025, 12, 20, 9, 30)
    result = get_active_program_entity(hass, config, current_time)
    assert result == "number.prog1_soc"
    
    # Test time outside window (would need another program to define end)
    # With single program, it runs all day
    current_time = datetime(2025, 12, 20, 13, 0)
    result = get_active_program_entity(hass, config, current_time)
    assert result == "number.prog1_soc"


def test_multiple_programs_priority():
    """Test that first matching program is returned."""
    hass = create_mock_hass({
        "input_datetime.prog1_start": "06:00",
        "input_datetime.prog2_start": "14:00",
    })
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG1_TIME_START: "input_datetime.prog1_start",
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_PROG2_TIME_START: "input_datetime.prog2_start",
    }
    
    # Test matching program 1
    current_time = datetime(2025, 12, 20, 8, 0)
    result = get_active_program_entity(hass, config, current_time)
    assert result == "number.prog1_soc"
    
    # Test matching program 2
    current_time = datetime(2025, 12, 20, 15, 30)
    result = get_active_program_entity(hass, config, current_time)
    assert result == "number.prog2_soc"
    
    # Test between programs (should match prog1, runs until prog2)
    current_time = datetime(2025, 12, 20, 13, 0)
    result = get_active_program_entity(hass, config, current_time)
    assert result == "number.prog1_soc"


def test_time_window_boundaries():
    """Test edge cases at time window boundaries."""
    hass = create_mock_hass({
        "input_datetime.prog1_start": "06:00",
        "input_datetime.prog2_start": "12:00",
    })
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG1_TIME_START: "input_datetime.prog1_start",
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_PROG2_TIME_START: "input_datetime.prog2_start",
    }
    
    # At start time (inclusive)
    current_time = datetime(2025, 12, 20, 6, 0)
    result = get_active_program_entity(hass, config, current_time)
    assert result == "number.prog1_soc"
    
    # One minute before end (inclusive)
    current_time = datetime(2025, 12, 20, 11, 59)
    result = get_active_program_entity(hass, config, current_time)
    assert result == "number.prog1_soc"
    
    # At end time (switches to next program)
    current_time = datetime(2025, 12, 20, 12, 0)
    result = get_active_program_entity(hass, config, current_time)
    assert result == "number.prog2_soc"


def test_midnight_crossing_window():
    """Test time windows that cross midnight."""
    hass = create_mock_hass({
        "input_datetime.prog1_start": "22:00",
        "input_datetime.prog2_start": "06:00",
    })
    config = {
        CONF_PROG1_SOC_ENTITY: "number.night_prog",
        CONF_PROG1_TIME_START: "input_datetime.prog1_start",
        CONF_PROG2_SOC_ENTITY: "number.morning_prog",
        CONF_PROG2_TIME_START: "input_datetime.prog2_start",
    }
    
    # Late evening (after start)
    current_time = datetime(2025, 12, 20, 23, 30)
    result = get_active_program_entity(hass, config, current_time)
    assert result == "number.night_prog"
    
    # Early morning (before end)
    current_time = datetime(2025, 12, 20, 3, 0)
    result = get_active_program_entity(hass, config, current_time)
    assert result == "number.night_prog"
    
    # After morning program start
    current_time = datetime(2025, 12, 20, 12, 0)
    result = get_active_program_entity(hass, config, current_time)
    assert result == "number.morning_prog"


def test_missing_time_entity():
    """Test program with time entity that doesn't exist."""
    hass = create_mock_hass({})  # No entities
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG1_TIME_START: "input_datetime.nonexistent",
    }
    
    current_time = datetime(2025, 12, 20, 10, 0)
    result = get_active_program_entity(hass, config, current_time)
    assert result is None


def test_invalid_time_format():
    """Test handling of invalid time formats."""
    hass = create_mock_hass({
        "input_datetime.prog1_start": "invalid"
    })
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG1_TIME_START: "input_datetime.prog1_start",
    }
    
    current_time = datetime(2025, 12, 20, 10, 0)
    result = get_active_program_entity(hass, config, current_time)
    # Should skip invalid program and return None
    assert result is None


def test_unavailable_entity_state():
    """Test handling of unavailable entity states."""
    hass = create_mock_hass({
        "input_datetime.prog1_start": "unavailable"
    })
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG1_TIME_START: "input_datetime.prog1_start",
    }
    
    current_time = datetime(2025, 12, 20, 10, 0)
    result = get_active_program_entity(hass, config, current_time)
    assert result is None


def test_all_six_programs():
    """Test configuration with all 6 programs."""
    hass = create_mock_hass({
        "input_datetime.prog1_start": "00:00",
        "input_datetime.prog2_start": "04:00",
        "input_datetime.prog3_start": "08:00",
    })
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1",
        CONF_PROG1_TIME_START: "input_datetime.prog1_start",
        CONF_PROG2_SOC_ENTITY: "number.prog2",
        CONF_PROG2_TIME_START: "input_datetime.prog2_start",
        CONF_PROG3_SOC_ENTITY: "number.prog3",
        CONF_PROG3_TIME_START: "input_datetime.prog3_start",
    }
    
    # Test matching each program
    test_cases = [
        (datetime(2025, 12, 20, 2, 0), "number.prog1"),
        (datetime(2025, 12, 20, 6, 0), "number.prog2"),
        (datetime(2025, 12, 20, 10, 0), "number.prog3"),
    ]
    
    for test_time, expected_entity in test_cases:
        result = get_active_program_entity(hass, config, test_time)
        assert result == expected_entity


def test_time_with_seconds():
    """Test time format with seconds (HH:MM:SS)."""
    hass = create_mock_hass({
        "input_datetime.prog1_start": "06:00:00"
    })
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG1_TIME_START: "input_datetime.prog1_start",
    }
    
    current_time = datetime(2025, 12, 20, 9, 30)
    result = get_active_program_entity(hass, config, current_time)
    assert result == "number.prog1_soc"


def test_iso_datetime_format():
    """Test parsing ISO datetime format from input_datetime entities."""
    hass = create_mock_hass({
        "input_datetime.prog1_start": "2025-12-20T06:00:00+00:00"
    })
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG1_TIME_START: "input_datetime.prog1_start",
    }
    
    current_time = datetime(2025, 12, 20, 9, 30)
    result = get_active_program_entity(hass, config, current_time)
    assert result == "number.prog1_soc"

