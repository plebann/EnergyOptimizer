"""Tests for helper functions."""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from custom_components.energy_optimizer.helpers import get_active_program_entity


def create_mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.states = MagicMock()
    return hass


def create_mock_config():
    """Create a mock configuration."""
    return {
        "prog1_soc_entity": "number.prog1_soc",
        "prog1_time_start_entity": "time.prog1_start",
        "prog2_soc_entity": "number.prog2_soc",
        "prog2_time_start_entity": "time.prog2_start",
        "prog3_soc_entity": "number.prog3_soc",
        "prog3_time_start_entity": "time.prog3_start",
    }


def create_time_state(time_value: str, domain: str = "time"):
    """Create a mock time entity state."""
    state = MagicMock()
    state.state = time_value
    state.domain = domain
    return state


class TestGetActiveProgramEntity:
    """Tests for get_active_program_entity function."""

    def test_no_programs_configured(self):
        """Test when no programs are configured."""
        hass = create_mock_hass()
        config = {}
        current_time = datetime(2024, 1, 1, 12, 0)
        
        result = get_active_program_entity(hass, config, current_time)
        
        assert result is None

    def test_single_program_active(self):
        """Test with single program active."""
        hass = create_mock_hass()
        config = create_mock_config()
        
        # Setup: Program 1 starts at 08:00
        hass.states.get.side_effect = lambda entity_id: {
            "time.prog1_start": create_time_state("08:00:00"),
            "time.prog2_start": create_time_state("unknown"),
            "time.prog3_start": create_time_state("unknown"),
        }.get(entity_id)
        
        current_time = datetime(2024, 1, 1, 10, 0)  # 10:00 AM
        
        result = get_active_program_entity(hass, config, current_time)
        
        assert result == "number.prog1_soc"

    def test_multiple_programs_morning(self):
        """Test with multiple programs, morning time."""
        hass = create_mock_hass()
        config = create_mock_config()
        
        # Setup: Prog1 at 06:00, Prog2 at 12:00, Prog3 at 18:00
        hass.states.get.side_effect = lambda entity_id: {
            "time.prog1_start": create_time_state("06:00:00"),
            "time.prog2_start": create_time_state("12:00:00"),
            "time.prog3_start": create_time_state("18:00:00"),
        }.get(entity_id)
        
        current_time = datetime(2024, 1, 1, 8, 0)  # 08:00 AM
        
        result = get_active_program_entity(hass, config, current_time)
        
        assert result == "number.prog1_soc"  # Active from 06:00 to 12:00

    def test_multiple_programs_afternoon(self):
        """Test with multiple programs, afternoon time."""
        hass = create_mock_hass()
        config = create_mock_config()
        
        hass.states.get.side_effect = lambda entity_id: {
            "time.prog1_start": create_time_state("06:00:00"),
            "time.prog2_start": create_time_state("12:00:00"),
            "time.prog3_start": create_time_state("18:00:00"),
        }.get(entity_id)
        
        current_time = datetime(2024, 1, 1, 14, 30)  # 02:30 PM
        
        result = get_active_program_entity(hass, config, current_time)
        
        assert result == "number.prog2_soc"  # Active from 12:00 to 18:00

    def test_multiple_programs_evening(self):
        """Test with multiple programs, evening time."""
        hass = create_mock_hass()
        config = create_mock_config()
        
        hass.states.get.side_effect = lambda entity_id: {
            "time.prog1_start": create_time_state("06:00:00"),
            "time.prog2_start": create_time_state("12:00:00"),
            "time.prog3_start": create_time_state("18:00:00"),
        }.get(entity_id)
        
        current_time = datetime(2024, 1, 1, 20, 0)  # 08:00 PM
        
        result = get_active_program_entity(hass, config, current_time)
        
        assert result == "number.prog3_soc"  # Active from 18:00 to 06:00 (next day)

    def test_midnight_crossing(self):
        """Test program window that crosses midnight."""
        hass = create_mock_hass()
        config = create_mock_config()
        
        hass.states.get.side_effect = lambda entity_id: {
            "time.prog1_start": create_time_state("06:00:00"),
            "time.prog2_start": create_time_state("12:00:00"),
            "time.prog3_start": create_time_state("22:00:00"),
        }.get(entity_id)
        
        # Test at 02:00 AM (should match prog3 which runs 22:00-06:00)
        current_time = datetime(2024, 1, 1, 2, 0)
        
        result = get_active_program_entity(hass, config, current_time)
        
        assert result == "number.prog3_soc"

    def test_iso_datetime_format(self):
        """Test parsing ISO datetime format (with T)."""
        hass = create_mock_hass()
        config = create_mock_config()
        
        hass.states.get.side_effect = lambda entity_id: {
            "time.prog1_start": create_time_state("2024-01-01T08:00:00"),
            "time.prog2_start": create_time_state("unknown"),
            "time.prog3_start": create_time_state("unknown"),
        }.get(entity_id)
        
        current_time = datetime(2024, 1, 1, 10, 0)
        
        result = get_active_program_entity(hass, config, current_time)
        
        assert result == "number.prog1_soc"

    def test_time_format_hh_mm(self):
        """Test parsing HH:MM format (without seconds)."""
        hass = create_mock_hass()
        config = create_mock_config()
        
        hass.states.get.side_effect = lambda entity_id: {
            "time.prog1_start": create_time_state("08:30"),
            "time.prog2_start": create_time_state("unknown"),
            "time.prog3_start": create_time_state("unknown"),
        }.get(entity_id)
        
        current_time = datetime(2024, 1, 1, 10, 0)
        
        result = get_active_program_entity(hass, config, current_time)
        
        assert result == "number.prog1_soc"

    def test_unavailable_time_entity(self):
        """Test with unavailable time entity."""
        hass = create_mock_hass()
        config = create_mock_config()
        
        hass.states.get.side_effect = lambda entity_id: {
            "time.prog1_start": create_time_state("unavailable"),
            "time.prog2_start": create_time_state("12:00:00"),
            "time.prog3_start": create_time_state("unknown"),
        }.get(entity_id)
        
        current_time = datetime(2024, 1, 1, 14, 0)
        
        result = get_active_program_entity(hass, config, current_time)
        
        # Should match prog2 (prog1 ignored due to unavailable state)
        assert result == "number.prog2_soc"

    def test_missing_time_entity(self):
        """Test with missing time entity."""
        hass = create_mock_hass()
        config = create_mock_config()
        
        hass.states.get.return_value = None
        
        current_time = datetime(2024, 1, 1, 10, 0)
        
        result = get_active_program_entity(hass, config, current_time)
        
        assert result is None

    def test_invalid_time_format(self):
        """Test with invalid time format."""
        hass = create_mock_hass()
        config = create_mock_config()
        
        hass.states.get.side_effect = lambda entity_id: {
            "time.prog1_start": create_time_state("invalid_time"),
            "time.prog2_start": create_time_state("12:00:00"),
            "time.prog3_start": create_time_state("unknown"),
        }.get(entity_id)
        
        current_time = datetime(2024, 1, 1, 14, 0)
        
        result = get_active_program_entity(hass, config, current_time)
        
        # Should match prog2 (prog1 ignored due to invalid format)
        assert result == "number.prog2_soc"

    def test_exact_start_time(self):
        """Test at exact program start time."""
        hass = create_mock_hass()
        config = create_mock_config()
        
        hass.states.get.side_effect = lambda entity_id: {
            "time.prog1_start": create_time_state("12:00:00"),
            "time.prog2_start": create_time_state("unknown"),
            "time.prog3_start": create_time_state("unknown"),
        }.get(entity_id)
        
        current_time = datetime(2024, 1, 1, 12, 0)  # Exactly 12:00
        
        result = get_active_program_entity(hass, config, current_time)
        
        assert result == "number.prog1_soc"

    def test_programs_sorted_by_time(self):
        """Test that programs are correctly sorted by start time."""
        hass = create_mock_hass()
        config = create_mock_config()
        
        # Configure programs in non-chronological order
        hass.states.get.side_effect = lambda entity_id: {
            "time.prog1_start": create_time_state("18:00:00"),  # Evening
            "time.prog2_start": create_time_state("06:00:00"),  # Morning
            "time.prog3_start": create_time_state("12:00:00"),  # Afternoon
        }.get(entity_id)
        
        current_time = datetime(2024, 1, 1, 8, 0)  # 08:00 AM
        
        result = get_active_program_entity(hass, config, current_time)
        
        # Should match prog2 (06:00-12:00) even though it's not first in config
        assert result == "number.prog2_soc"
