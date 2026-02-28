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
