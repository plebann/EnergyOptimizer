"""Tests for PV forecast utility behavior."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.energy_optimizer.const import (
    CONF_PV_FORECAST_TODAY,
    CONF_PV_FORECAST_TOMORROW,
)
from custom_components.energy_optimizer.utils.pv_forecast import (
    _collect_pv_forecast_hourly_kwh,
    get_pv_compensation_factor,
    get_morning_pv_forecast,
    get_pv_forecast,
)


@pytest.mark.unit
def test_collect_pv_forecast_empty_window_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return empty mapping when start and end hour define a zero-width window."""
    monkeypatch.setattr(
        dt_util,
        "now",
        lambda: datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc),
    )
    hass = MagicMock()
    pv_state = MagicMock()
    pv_state.attributes = {
        "detailedForecast": [
            {"period_start": "2026-02-27T13:00:00+01:00", "pv_estimate": 1.2},
        ]
    }
    hass.states.get.return_value = pv_state

    config = {
        CONF_PV_FORECAST_TODAY: "sensor.pv_today",
        CONF_PV_FORECAST_TOMORROW: "sensor.pv_tomorrow",
    }

    hourly = _collect_pv_forecast_hourly_kwh(
        hass,
        config,
        start_hour=13,
        end_hour=13,
    )

    assert hourly == {}


@pytest.mark.unit
def test_morning_pv_forecast_uses_daylight_fallback_when_hourly_data_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the aggregate forecast across full daylight hours without sufficiency."""
    now = datetime(2026, 8, 14, 5, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(dt_util, "now", lambda: now)
    hass = MagicMock()

    aggregate = MagicMock()
    aggregate.state = "120"
    aggregate.attributes = {}
    aggregate.last_updated = now
    sun = MagicMock()
    sun.attributes = {
        "next_rising": "2026-08-14T06:40:00+00:00",
        "next_setting": "2026-08-14T20:15:00+00:00",
    }
    hass.states.get.side_effect = lambda entity_id: {
        "sensor.pv_today": aggregate,
        "sun.sun": sun,
    }.get(entity_id)

    forecast = get_morning_pv_forecast(
        hass,
        {CONF_PV_FORECAST_TODAY: "sensor.pv_today"},
        start_hour=5,
        end_hour=12,
        apply_efficiency=False,
    )

    assert forecast.status == "missing_hourly"
    assert forecast.method == "daylight_uniform"
    assert forecast.failure_reason == "hourly_attribute_missing"
    assert forecast.audit_details()["hourly_payload_present"] is False
    assert forecast.sufficiency_available is False
    assert forecast.daylight_hours == [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    assert forecast.total_kwh == pytest.approx(46.153846)
    assert forecast.hourly_kwh[7] == pytest.approx(9.230769)


@pytest.mark.unit
def test_morning_pv_forecast_accepts_zero_hourly_values_when_aggregate_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treat matching zero forecasts as valid hourly data, not missing PV."""
    now = datetime(2026, 8, 14, 5, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(dt_util, "now", lambda: now)
    hass = MagicMock()
    aggregate = MagicMock()
    aggregate.state = "0"
    aggregate.last_updated = now
    aggregate.attributes = {
        "detailedForecast": [
            {"period_start": "2026-08-14T07:00:00+00:00", "pv_estimate": 0.0},
        ]
    }
    hass.states.get.return_value = aggregate

    forecast = get_morning_pv_forecast(
        hass,
        {CONF_PV_FORECAST_TODAY: "sensor.pv_today"},
        start_hour=5,
        end_hour=12,
        apply_efficiency=False,
    )

    assert forecast.status == "valid_hourly"
    assert forecast.method == "detailed_forecast_fallback"
    assert forecast.selected_attribute == "detailedForecast"
    assert forecast.sufficiency_available is True
    assert forecast.total_kwh == 0.0


@pytest.mark.unit
def test_morning_pv_forecast_uses_half_aggregate_when_hourly_data_disagrees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the second fallback when aggregate and hourly forecasts diverge."""
    now = datetime(2026, 8, 14, 5, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(dt_util, "now", lambda: now)
    hass = MagicMock()
    aggregate = MagicMock()
    aggregate.state = "10"
    aggregate.last_updated = now
    aggregate.attributes = {
        "detailedForecast": [
            {"period_start": "2026-08-14T07:00:00+00:00", "pv_estimate": 1.0},
        ]
    }
    hass.states.get.side_effect = lambda entity_id: (
        aggregate if entity_id == "sensor.pv_today" else None
    )

    forecast = get_morning_pv_forecast(
        hass,
        {CONF_PV_FORECAST_TODAY: "sensor.pv_today"},
        start_hour=5,
        end_hour=12,
        apply_efficiency=False,
    )

    assert forecast.status == "invalid_hourly"
    assert forecast.method == "half_aggregate"
    assert forecast.failure_reason == "hourly_aggregate_mismatch"
    assert forecast.total_kwh == 5.0
    assert forecast.sufficiency_available is False


@pytest.mark.unit
def test_morning_pv_forecast_records_valid_detailed_hourly_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Record scalar provenance for accepted detailedHourly data only."""
    now = datetime(2026, 8, 14, 5, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(dt_util, "now", lambda: now)
    hass = MagicMock()
    aggregate = MagicMock()
    aggregate.state = "2"
    aggregate.last_updated = now
    aggregate.last_changed = datetime(2026, 8, 14, 4, 0, tzinfo=timezone.utc)
    aggregate.attributes = {
        "detailedHourly": [
            {"period_start": "2026-08-14T07:00:00+00:00", "pv_estimate": 1.0},
            {"period_start": "2026-08-14T10:00:00+02:00", "pv_estimate": 1.0},
        ]
    }
    hass.states.get.return_value = aggregate

    forecast = get_morning_pv_forecast(
        hass,
        {CONF_PV_FORECAST_TODAY: "sensor.pv_today"},
        start_hour=5,
        end_hour=12,
        apply_efficiency=False,
    )

    details = forecast.audit_details()
    assert forecast.status == "valid_hourly"
    assert forecast.method == "detailed_hourly"
    assert forecast.sufficiency_available is True
    assert details["source_entity"] == "sensor.pv_today"
    assert details["source_state"] == "2"
    assert details["selected_attribute"] == "detailedHourly"
    assert details["hourly_payload_type"] == "list"
    assert details["hourly_payload_length"] == 2
    assert details["first_period_start"] == "2026-08-14T07:00:00+00:00"
    assert details["last_period_start"] == "2026-08-14T10:00:00+02:00"
    assert details["evaluation_time_utc"] == "2026-08-14T05:00:00+00:00"
    assert details["failure_reason"] is None
    assert aggregate.attributes["detailedHourly"] not in details.values()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("attributes", "reason"),
    [
        ({"detailedHourly": []}, "hourly_empty"),
        ({"detailedHourly": "invalid"}, "hourly_not_list"),
        ({"detailedForecast": "invalid"}, "hourly_not_list"),
        ({"detailedHourly": [1]}, "record_not_mapping"),
        ({"detailedHourly": [{"pv_estimate": 1.0}]}, "period_start_missing"),
        (
            {"detailedHourly": [{"period_start": "not-a-date", "pv_estimate": 1.0}]},
            "period_start_invalid",
        ),
        (
            {"detailedHourly": [{"period_start": "2026-08-14T07:00:00+00:00"}]},
            "pv_estimate_missing",
        ),
        (
            {
                "detailedHourly": [
                    {
                        "period_start": "2026-08-14T07:00:00+00:00",
                        "pv_estimate": "invalid",
                    }
                ]
            },
            "pv_estimate_invalid",
        ),
        (
            {
                "detailedHourly": [
                    {
                        "period_start": "2026-08-13T07:00:00+00:00",
                        "pv_estimate": 1.0,
                    }
                ]
            },
            "record_local_date_mismatch",
        ),
    ],
)
def test_morning_pv_forecast_records_hourly_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
    attributes: dict[str, object],
    reason: str,
) -> None:
    """Classify malformed hourly payloads with replay-stable reason codes."""
    now = datetime(2026, 8, 14, 5, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(dt_util, "now", lambda: now)
    hass = MagicMock()
    aggregate = MagicMock()
    aggregate.state = "2"
    aggregate.last_updated = now
    aggregate.attributes = attributes
    hass.states.get.return_value = aggregate

    forecast = get_morning_pv_forecast(
        hass,
        {CONF_PV_FORECAST_TODAY: "sensor.pv_today"},
        start_hour=5,
        end_hour=12,
        apply_efficiency=False,
    )

    assert forecast.status in {"missing_hourly", "invalid_hourly"}
    assert forecast.failure_reason == reason
    assert forecast.sufficiency_available is False


@pytest.mark.unit
def test_morning_pv_forecast_marks_previous_day_update_as_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not use matching hourly entries from a stale sensor update."""
    now = datetime(2026, 8, 14, 5, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(dt_util, "now", lambda: now)
    hass = MagicMock()
    aggregate = MagicMock()
    aggregate.state = "1"
    aggregate.last_updated = datetime(2026, 8, 13, 23, 59, tzinfo=timezone.utc)
    aggregate.attributes = {
        "detailedForecast": [
            {"period_start": "2026-08-14T07:00:00+00:00", "pv_estimate": 1.0},
        ]
    }
    hass.states.get.side_effect = lambda entity_id: (
        aggregate if entity_id == "sensor.pv_today" else None
    )

    forecast = get_morning_pv_forecast(
        hass,
        {CONF_PV_FORECAST_TODAY: "sensor.pv_today"},
        start_hour=5,
        end_hour=12,
        apply_efficiency=False,
    )

    assert forecast.status == "stale_hourly"
    assert forecast.method == "half_aggregate"
    assert forecast.failure_reason == "stale_sensor_update"
    assert forecast.total_kwh == 0.5


@pytest.mark.unit
def test_morning_pv_forecast_uses_todays_sunrise_after_dawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use today's sunrise when sun.sun already reports tomorrow's next rise."""
    now = datetime(2026, 8, 14, 7, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(dt_util, "now", lambda: now)
    monkeypatch.setattr(
        "custom_components.energy_optimizer.utils.pv_forecast.get_astral_event_date",
        lambda hass, event, date: datetime(2026, 8, 14, 6, 40, tzinfo=timezone.utc),
    )
    hass = MagicMock()
    aggregate = MagicMock()
    aggregate.state = "120"
    aggregate.attributes = {}
    aggregate.last_updated = now
    sun = MagicMock()
    sun.attributes = {
        "next_rising": "2026-08-15T06:41:00+00:00",
        "next_setting": "2026-08-14T20:15:00+00:00",
    }
    hass.states.get.side_effect = lambda entity_id: {
        "sensor.pv_today": aggregate,
        "sun.sun": sun,
    }.get(entity_id)

    forecast = get_morning_pv_forecast(
        hass,
        {CONF_PV_FORECAST_TODAY: "sensor.pv_today"},
        start_hour=7,
        end_hour=12,
        apply_efficiency=False,
    )

    assert forecast.method == "daylight_uniform"
    assert forecast.total_kwh == pytest.approx(46.153846)


@pytest.mark.unit
def test_morning_pv_forecast_rejects_negative_aggregate() -> None:
    """Continue safely without PV when the aggregate forecast is negative."""
    hass = MagicMock()
    aggregate = MagicMock()
    aggregate.state = "-1"
    hass.states.get.return_value = aggregate

    forecast = get_morning_pv_forecast(
        hass,
        {CONF_PV_FORECAST_TODAY: "sensor.pv_today"},
        start_hour=5,
        end_hour=12,
    )

    assert forecast.status == "invalid_forecast"
    assert forecast.total_kwh == 0.0


@pytest.mark.unit
def test_get_pv_forecast_empty_window_returns_zero_and_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return zero total and empty mapping for a zero-width PV window."""
    monkeypatch.setattr(
        dt_util,
        "now",
        lambda: datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc),
    )
    hass = MagicMock()
    pv_state = MagicMock()
    pv_state.attributes = {
        "detailedForecast": [
            {"period_start": "2026-02-27T13:00:00+01:00", "pv_estimate": 2.0},
        ]
    }
    hass.states.get.return_value = pv_state

    config = {
        CONF_PV_FORECAST_TODAY: "sensor.pv_today",
        CONF_PV_FORECAST_TOMORROW: "sensor.pv_tomorrow",
    }

    total, hourly = get_pv_forecast(
        hass,
        config,
        start_hour=13,
        end_hour=13,
        apply_efficiency=False,
    )

    assert total == pytest.approx(0.0)
    assert hourly == {}


@pytest.mark.unit
def test_collect_pv_forecast_ignores_hours_outside_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ignore forecast entries that are outside the requested window."""
    monkeypatch.setattr(
        dt_util,
        "now",
        lambda: datetime(2026, 2, 27, 6, 0, tzinfo=timezone.utc),
    )
    hass = MagicMock()
    pv_state = MagicMock()
    pv_state.attributes = {
        "detailedForecast": [
            {"period_start": "2026-02-27T10:00:00+01:00", "pv_estimate": 1.0},
            {"period_start": "2026-02-27T11:00:00+01:00", "pv_estimate": 2.0},
            {"period_start": "2026-02-27T12:00:00+01:00", "pv_estimate": 3.0},
            {"period_start": "2026-02-27T15:00:00+01:00", "pv_estimate": 4.0},
        ]
    }
    hass.states.get.return_value = pv_state

    config = {
        CONF_PV_FORECAST_TODAY: "sensor.pv_today",
        CONF_PV_FORECAST_TOMORROW: "sensor.pv_tomorrow",
    }

    hourly = _collect_pv_forecast_hourly_kwh(
        hass,
        config,
        start_hour=11,
        end_hour=13,
    )

    assert set(hourly.keys()) == {11, 12}
    assert hourly[11] == pytest.approx(2.0)
    assert hourly[12] == pytest.approx(3.0)


@pytest.mark.unit
def test_collect_pv_forecast_wrap_window_after_start_uses_today_and_tomorrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use both today and tomorrow forecast for windows crossing midnight."""
    monkeypatch.setattr(
        dt_util,
        "now",
        lambda: datetime(2026, 2, 28, 23, 9, tzinfo=timezone.utc),
    )
    hass = MagicMock()

    today_state = MagicMock()
    today_state.attributes = {
        "detailedForecast": [
            {"period_start": "2026-02-28T22:00:00+01:00", "pv_estimate": 1.5},
            {"period_start": "2026-02-28T23:00:00+01:00", "pv_estimate": 2.5},
        ]
    }
    tomorrow_state = MagicMock()
    tomorrow_state.attributes = {
        "detailedForecast": [
            {"period_start": "2026-03-01T00:00:00+01:00", "pv_estimate": 3.0},
            {"period_start": "2026-03-01T12:00:00+01:00", "pv_estimate": 4.0},
        ]
    }

    sensor_states = {
        "sensor.pv_today": today_state,
        "sensor.pv_tomorrow": tomorrow_state,
    }
    hass.states.get.side_effect = lambda entity_id: sensor_states.get(entity_id)

    config = {
        CONF_PV_FORECAST_TODAY: "sensor.pv_today",
        CONF_PV_FORECAST_TOMORROW: "sensor.pv_tomorrow",
    }

    hourly = _collect_pv_forecast_hourly_kwh(
        hass,
        config,
        start_hour=22,
        end_hour=13,
    )

    assert set(hourly.keys()) == {22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}
    assert hourly[22] == pytest.approx(1.5)
    assert hourly[23] == pytest.approx(2.5)
    assert hourly[0] == pytest.approx(3.0)
    assert hourly[12] == pytest.approx(4.0)


@pytest.mark.unit
def test_get_pv_compensation_factor_respects_disabled_switch() -> None:
    """Return None when compensation usage switch is off."""
    hass = MagicMock()
    hass.config_entries = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {}
    entry.options = {}
    hass.config_entries.async_get_entry.return_value = entry

    sensor = MagicMock()
    sensor.native_value = 0.87
    pv_comp_switch = MagicMock()
    pv_comp_switch.is_on = False
    hass.data = {
        "energy_optimizer": {
            "entry-1": {
                "pv_forecast_compensation_sensor": sensor,
                "pv_forecast_compensation_switch": pv_comp_switch,
            }
        }
    }

    assert get_pv_compensation_factor(hass, "entry-1") is None


@pytest.mark.unit
def test_get_pv_compensation_factor_defaults_enabled_when_missing_flag() -> None:
    """Use sensor value when toggle is missing to preserve backward compatibility."""
    hass = MagicMock()
    hass.config_entries = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {}
    entry.options = {}
    hass.config_entries.async_get_entry.return_value = entry

    sensor = MagicMock()
    sensor.native_value = 0.91
    hass.data = {"energy_optimizer": {"entry-1": {"pv_forecast_compensation_sensor": sensor}}}

    assert get_pv_compensation_factor(hass, "entry-1") == pytest.approx(0.91)


@pytest.mark.unit
def test_get_pv_compensation_factor_enabled_switch_returns_sensor_value() -> None:
    """Use sensor value when compensation usage switch is on."""
    hass = MagicMock()
    hass.config_entries = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {}
    entry.options = {}
    hass.config_entries.async_get_entry.return_value = entry

    sensor = MagicMock()
    sensor.native_value = 1.03
    pv_comp_switch = MagicMock()
    pv_comp_switch.is_on = True
    hass.data = {
        "energy_optimizer": {
            "entry-1": {
                "pv_forecast_compensation_sensor": sensor,
                "pv_forecast_compensation_switch": pv_comp_switch,
            }
        }
    }

    assert get_pv_compensation_factor(hass, "entry-1") == pytest.approx(1.03)
