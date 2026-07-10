"""Tests for helper functions."""
from datetime import datetime, time
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util

from custom_components.energy_optimizer.const import (
    CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR,
    CONF_EVENING_MAX_PRICE_HOUR_SENSOR,
    CONF_HIGH_TARIFF_END_HOUR_SENSOR,
    CONF_HIGH_TARIFF_START_HOUR_SENSOR,
    CONF_MORNING_MAX_PRICE_HOUR_SENSOR,
)
from custom_components.energy_optimizer.helpers import (
    _parse_time_from_state_value,
    get_active_program_entity,
    resolve_daytime_min_price_time,
    resolve_evening_max_price_hour,
    resolve_evening_second_max_price_hour,
    resolve_morning_max_price_hour,
    resolve_night_buy_window_duration_hours,
    resolve_night_buy_window_start_hour,
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


def test_resolve_evening_max_price_hour_from_timestamp_sensor() -> None:
    """Resolve evening hour from ISO timestamp sensor state."""
    original_tz = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(ZoneInfo("Europe/Warsaw"))
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state("2026-02-26T18:00:00+01:00", domain="sensor")

    config = {CONF_EVENING_MAX_PRICE_HOUR_SENSOR: "sensor.today_max_price_hour_start_timestamp"}

    try:
        assert resolve_evening_max_price_hour(hass, config, default_hour=17) == 18
    finally:
        dt_util.set_default_time_zone(original_tz)


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


# ---------------------------------------------------------------------------
# Tests for entry_id-based resolve_* paths
# ---------------------------------------------------------------------------

_INTERNAL_SENSOR_PATCH = (
    "custom_components.energy_optimizer.helpers.get_internal_sensor_entity_id"
)


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_evening_max_price_hour_from_internal_sensor_hh_mm(
    mock_get_internal: MagicMock,
) -> None:
    """resolve_evening_max_price_hour reads start hour from internal sensor state (HH:MM)."""
    mock_get_internal.return_value = "sensor.eo_evening_sell_window"
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state("19:00", domain="sensor")

    result = resolve_evening_max_price_hour(hass, {}, entry_id="entry_abc", default_hour=17)

    assert result == 19
    mock_get_internal.assert_called_once()


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_evening_max_price_hour_from_internal_sensor_hh_mm_range(
    mock_get_internal: MagicMock,
) -> None:
    """resolve_evening_max_price_hour extracts start hour from HH:MM-HH:MM range state."""
    mock_get_internal.return_value = "sensor.eo_evening_sell_window"
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state("18:00-22:00", domain="sensor")

    result = resolve_evening_max_price_hour(hass, {}, entry_id="entry_abc", default_hour=17)

    assert result == 18


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_evening_max_price_hour_internal_sensor_not_found_falls_back(
    mock_get_internal: MagicMock,
) -> None:
    """Falls back to config sensor when internal window entity is not in registry."""
    mock_get_internal.return_value = None
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state("20:00", domain="sensor")
    config = {CONF_EVENING_MAX_PRICE_HOUR_SENSOR: "sensor.evening_max"}

    result = resolve_evening_max_price_hour(hass, config, entry_id="entry_abc", default_hour=17)

    assert result == 20


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_evening_second_max_price_hour_from_internal_sensor_attribute(
    mock_get_internal: MagicMock,
) -> None:
    """resolve_evening_second_max_price_hour reads second_window_start attribute."""
    mock_get_internal.return_value = "sensor.eo_evening_sell_window"
    hass = create_mock_hass()
    state = MagicMock()
    state.state = "18:00-22:00"
    state.attributes = {"second_window_start": "20:00"}
    hass.states.get.return_value = state

    result = resolve_evening_second_max_price_hour(hass, {}, entry_id="entry_abc")

    assert result == 20


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_evening_second_max_price_hour_internal_sensor_not_found_returns_none(
    mock_get_internal: MagicMock,
) -> None:
    """Returns None when internal sensor is unavailable and no config sensor is set."""
    mock_get_internal.return_value = None
    hass = create_mock_hass()
    hass.states.get.return_value = None

    result = resolve_evening_second_max_price_hour(hass, {}, entry_id="entry_abc")

    assert result is None


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_morning_max_price_hour_from_internal_sensor(
    mock_get_internal: MagicMock,
) -> None:
    """resolve_morning_max_price_hour reads start hour from internal morning window sensor."""
    mock_get_internal.return_value = "sensor.eo_morning_sell_window"
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state("07:30", domain="sensor")

    result = resolve_morning_max_price_hour(hass, {}, entry_id="entry_abc", default_hour=8)

    assert result == 7


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_morning_max_price_hour_from_internal_sensor_hh_mm_range(
    mock_get_internal: MagicMock,
) -> None:
    """resolve_morning_max_price_hour extracts start hour from HH:MM-HH:MM range state."""
    mock_get_internal.return_value = "sensor.eo_morning_sell_window"
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state("06:00-09:00", domain="sensor")

    result = resolve_morning_max_price_hour(hass, {}, entry_id="entry_abc", default_hour=8)

    assert result == 6


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_night_buy_window_start_hour_from_internal_sensor(
    mock_get_internal: MagicMock,
) -> None:
    """resolve_night_buy_window_start_hour reads the night window start from state."""
    mock_get_internal.return_value = "sensor.eo_night_buy_window"
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state("02:00", domain="sensor")

    result = resolve_night_buy_window_start_hour(
        hass,
        {},
        entry_id="entry_abc",
        default_hour=4,
    )

    assert result == 2


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_night_buy_window_start_hour_falls_back_to_default(
    mock_get_internal: MagicMock,
) -> None:
    """resolve_night_buy_window_start_hour falls back when the sensor is unavailable."""
    mock_get_internal.return_value = None
    hass = create_mock_hass()
    hass.states.get.return_value = None

    result = resolve_night_buy_window_start_hour(
        hass,
        {},
        entry_id="entry_abc",
        default_hour=4,
    )

    assert result == 4


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_night_buy_window_duration_hours_from_internal_sensor(
    mock_get_internal: MagicMock,
) -> None:
    """resolve_night_buy_window_duration_hours reads the duration attribute."""
    mock_get_internal.return_value = "sensor.eo_night_buy_window"
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state(
        "02:00",
        domain="sensor",
        attributes={"duration_hours": 4},
    )

    result = resolve_night_buy_window_duration_hours(
        hass,
        {},
        entry_id="entry_abc",
        default_hours=2.0,
    )

    assert result == pytest.approx(4.0)


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_night_buy_window_duration_hours_falls_back_to_default(
    mock_get_internal: MagicMock,
) -> None:
    """resolve_night_buy_window_duration_hours falls back when missing."""
    mock_get_internal.return_value = "sensor.eo_night_buy_window"
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state("02:00", domain="sensor")

    result = resolve_night_buy_window_duration_hours(
        hass,
        {},
        entry_id="entry_abc",
        default_hours=2.0,
    )

    assert result == pytest.approx(2.0)


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_daytime_min_price_time_from_internal_sensor_hh_mm(
    mock_get_internal: MagicMock,
) -> None:
    """resolve_daytime_min_price_time reads time from internal midday window sensor."""
    mock_get_internal.return_value = "sensor.eo_midday_sell_window"
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state("11:30", domain="sensor")

    result = resolve_daytime_min_price_time(hass, {}, entry_id="entry_abc", default_time="12:00")

    assert result == time(11, 30)


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_daytime_min_price_time_from_internal_sensor_hh_mm_range(
    mock_get_internal: MagicMock,
) -> None:
    """resolve_daytime_min_price_time extracts start time from HH:MM-HH:MM range state."""
    mock_get_internal.return_value = "sensor.eo_midday_sell_window"
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state("11:00-13:00", domain="sensor")

    result = resolve_daytime_min_price_time(hass, {}, entry_id="entry_abc", default_time="12:00")

    assert result == time(11, 0)


@patch(_INTERNAL_SENSOR_PATCH)
def test_resolve_daytime_min_price_time_internal_sensor_not_found_falls_back(
    mock_get_internal: MagicMock,
) -> None:
    """Falls back to config sensor when internal midday window entity is not in registry."""
    mock_get_internal.return_value = None
    hass = create_mock_hass()
    hass.states.get.return_value = create_time_state("10:00", domain="sensor")
    config = {CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR: "sensor.daytime_min"}

    result = resolve_daytime_min_price_time(hass, config, entry_id="entry_abc", default_time="12:00")

    assert result == time(10, 0)
