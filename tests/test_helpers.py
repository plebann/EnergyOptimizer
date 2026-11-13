"""Tests for helper functions."""
from datetime import datetime, time
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util

from custom_components.energy_optimizer.const import (
    CONF_HIGH_TARIFF_END_HOUR_SENSOR,
    CONF_HIGH_TARIFF_START_HOUR_SENSOR,
)
from custom_components.energy_optimizer.helpers import (
    _parse_time_from_state_value,
    get_active_program_entity,
    resolve_tariff_end_hour,
    resolve_tariff_start_hour,
)


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


def create_time_state(
    time_value: str,
    domain: str = "time",
    *,
    attributes: dict[str, object] | None = None,
):
    """Create a mock time entity state."""
    state = MagicMock()
    state.state = time_value
    state.domain = domain
    state.attributes = attributes or {}
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



def test_resolve_high_tariff_end_hour_from_timestamp_sensor() -> None:
    """Resolve high tariff end hour from ISO timestamp sensor state."""
    original_tz = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(ZoneInfo("Europe/Warsaw"))
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state("2026-02-26T13:00:00+01:00", domain="sensor")

    config = {CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.today_min_price_hour_end_timestamp"}

    try:
        assert resolve_tariff_end_hour(hass, config, default_hour=13) == 13
    finally:
        dt_util.set_default_time_zone(original_tz)


def test_resolve_high_tariff_start_hour_from_time_string_sensor() -> None:
    """Resolve high tariff start hour from HH:MM sensor state."""
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state("15:00", domain="sensor")

    config = {CONF_HIGH_TARIFF_START_HOUR_SENSOR: "sensor.today_min_price_hour_start"}

    assert resolve_tariff_start_hour(hass, config, default_hour=15) == 15


# ---------------------------------------------------------------------------
# Tests for _parse_time_from_state_value
# ---------------------------------------------------------------------------

class TestParseTimeFromStateValue:
    """Tests for _parse_time_from_state_value."""

    def test_hh_mm_range_returns_start_time(self) -> None:
        """'HH:MM-HH:MM' range returns the start segment as a time object."""
        result = _parse_time_from_state_value("18:00-22:00")
        assert result == time(18, 0)

    def test_hh_mm_range_with_spaces_returns_start_time(self) -> None:
        """'HH:MM - HH:MM' range with surrounding spaces returns start time."""
        result = _parse_time_from_state_value("18:30 - 21:00")
        assert result == time(18, 30)

    def test_hh_mm_format(self) -> None:
        """Plain 'HH:MM' format is parsed to the correct time."""
        result = _parse_time_from_state_value("15:30")
        assert result == time(15, 30)

    def test_hh_mm_ss_format(self) -> None:
        """'HH:MM:SS' format is parsed to the correct time (seconds ignored)."""
        result = _parse_time_from_state_value("08:45:00")
        assert result == time(8, 45)

    def test_iso_datetime_format(self) -> None:
        """ISO datetime string is converted to local time."""
        original_tz = dt_util.get_default_time_zone()
        dt_util.set_default_time_zone(ZoneInfo("UTC"))
        try:
            result = _parse_time_from_state_value("2026-02-26T18:00:00+00:00")
            assert result == time(18, 0)
        finally:
            dt_util.set_default_time_zone(original_tz)

    def test_invalid_format_returns_none(self) -> None:
        """Unrecognised string returns None."""
        assert _parse_time_from_state_value("not-a-time") is None

    def test_unknown_state_returns_none(self) -> None:
        """HA sentinel values 'unknown' and 'unavailable' return None."""
        assert _parse_time_from_state_value("unknown") is None
        assert _parse_time_from_state_value("unavailable") is None

    def test_midnight_time(self) -> None:
        """Midnight boundary '00:00' is parsed correctly."""
        result = _parse_time_from_state_value("00:00")
        assert result == time(0, 0)

    def test_hh_mm_range_non_zero_minutes_start(self) -> None:
        """'HH:MM-HH:MM' range with non-zero start minutes is handled."""
        result = _parse_time_from_state_value("7:45-9:00")
        assert result == time(7, 45)
