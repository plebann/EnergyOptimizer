"""Tests for time-based program selection logic."""
import pytest
from datetime import datetime, time

# Import the function to test
import sys
sys.path.insert(0, '../custom_components/energy_optimizer')
from custom_components.energy_optimizer import get_active_program_entity
from custom_components.energy_optimizer.const import (
    CONF_PROG1_SOC_ENTITY, CONF_PROG1_TIME_START,
    CONF_PROG2_SOC_ENTITY, CONF_PROG2_TIME_START,
    CONF_PROG3_SOC_ENTITY, CONF_PROG3_TIME_START,
)


def test_no_programs_configured():
    """Test when no programs are configured."""
    config = {}
    current_time = datetime(2025, 12, 20, 10, 0)
    
    result = get_active_program_entity(config, current_time)
    assert result is None


def test_single_program_time_match():
    """Test matching a single configured program."""
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG1_TIME_START: "06:00",
    }
    
    # Test time within window
    current_time = datetime(2025, 12, 20, 9, 30)
    result = get_active_program_entity(config, current_time)
    assert result == "number.prog1_soc"
    
    # Test time outside window
    current_time = datetime(2025, 12, 20, 13, 0)
    result = get_active_program_entity(config, current_time)
    assert result is None


def test_multiple_programs_priority():
    """Test that first matching program is returned."""
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG1_TIME_START: "06:00",
        CONF_PROG2_SOC_ENTITY: "number.prog2_soc",
        CONF_PROG2_TIME_START: "14:00",
    }
    
    # Test matching program 1
    current_time = datetime(2025, 12, 20, 8, 0)
    result = get_active_program_entity(config, current_time)
    assert result == "number.prog1_soc"
    
    # Test matching program 2
    current_time = datetime(2025, 12, 20, 15, 30)
    result = get_active_program_entity(config, current_time)
    assert result == "number.prog2_soc"
    
    # Test no match
    current_time = datetime(2025, 12, 20, 13, 0)
    result = get_active_program_entity(config, current_time)
    assert result is None


def test_time_window_boundaries():
    """Test edge cases at time window boundaries."""
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG1_TIME_START: "06:00",
    }
    
    # At start time (inclusive)
    current_time = datetime(2025, 12, 20, 6, 0)
    result = get_active_program_entity(config, current_time)
    assert result == "number.prog1_soc"
    
    # One minute before end (inclusive)
    current_time = datetime(2025, 12, 20, 11, 59)
    result = get_active_program_entity(config, current_time)
    assert result == "number.prog1_soc"
    
    # At end time (exclusive)
    current_time = datetime(2025, 12, 20, 12, 0)
    result = get_active_program_entity(config, current_time)
    assert result is None


def test_midnight_crossing_window():
    """Test time windows that cross midnight."""
    config = {
        CONF_PROG1_SOC_ENTITY: "number.night_prog",
        CONF_PROG1_TIME_START: "22:00",
    }
    
    # Late evening (after start)
    current_time = datetime(2025, 12, 20, 23, 30)
    result = get_active_program_entity(config, current_time)
    assert result == "number.night_prog"
    
    # Early morning (before end)
    current_time = datetime(2025, 12, 20, 3, 0)
    result = get_active_program_entity(config, current_time)
    assert result == "number.night_prog"
    
    # Outside window
    current_time = datetime(2025, 12, 20, 12, 0)
    result = get_active_program_entity(config, current_time)
    assert result is None


def test_missing_time_windows():
    """Test program with SOC entity but no time windows."""
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        # No time windows configured
    }
    
    current_time = datetime(2025, 12, 20, 10, 0)
    result = get_active_program_entity(config, current_time)
    assert result is None


def test_time_object_input():
    """Test with time objects instead of strings."""
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG1_TIME_START: time(6, 0),
    }
    
    current_time = datetime(2025, 12, 20, 9, 30)
    result = get_active_program_entity(config, current_time)
    assert result == "number.prog1_soc"


def test_invalid_time_format():
    """Test handling of invalid time formats."""
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1_soc",
        CONF_PROG1_TIME_START: "invalid",
    }
    
    current_time = datetime(2025, 12, 20, 10, 0)
    result = get_active_program_entity(config, current_time)
    # Should skip invalid program and return None
    assert result is None


def test_all_six_programs():
    """Test configuration with all 6 programs."""
    config = {
        CONF_PROG1_SOC_ENTITY: "number.prog1",
        CONF_PROG1_TIME_START: "00:00",
        CONF_PROG2_SOC_ENTITY: "number.prog2",
        CONF_PROG2_TIME_START: "04:00",
        CONF_PROG3_SOC_ENTITY: "number.prog3",
        CONF_PROG3_TIME_START: "08:00",
    }
    
    # Test matching each program
    test_cases = [
        (datetime(2025, 12, 20, 2, 0), "number.prog1"),
        (datetime(2025, 12, 20, 6, 0), "number.prog2"),
        (datetime(2025, 12, 20, 10, 0), "number.prog3"),
    ]
    
    for test_time, expected_entity in test_cases:
        result = get_active_program_entity(config, test_time)
        assert result == expected_entity
