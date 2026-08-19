"""Tests for compact optimization history storage."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from homeassistant.util import dt as dt_util

from custom_components.energy_optimizer.entities.sensors.tracking import (
    _HISTORY_MAX_BYTES,
    OptimizationHistorySensor,
)
from custom_components.energy_optimizer.decision_engine.sell_base import BaseSellStrategy
from custom_components.energy_optimizer.utils.logging import DecisionOutcome


def _history_sensor() -> OptimizationHistorySensor:
    """Create an uninitialized history sensor suitable for unit testing."""
    sensor = object.__new__(OptimizationHistorySensor)
    sensor._history = []
    sensor._attr_native_value = "No optimizations yet"
    sensor.async_write_ha_state = MagicMock()
    return sensor


def test_history_entry_is_compact_and_includes_decision_window() -> None:
    """History stores a compact decision projection rather than full details."""
    sensor = _history_sensor()

    sensor.add_entry(
        "Morning Grid Charge",
        {
            "result": "Battery scheduled to charge to 80%",
            "target_soc": 80.0,
            "charge_current_a": 12.5,
            "to_charge_kwh": 3.2,
            "needed_reserve_kwh": 1.4,
            "required_kwh": 5.6,
        },
        action_type="charge_scheduled",
        reason="Gap requires grid charge",
        windows=[["cr", 6, "nb_e", 13, "db_s", False]],
    )

    entry = sensor.extra_state_attributes["history"][0]
    assert dt_util.parse_datetime(entry["t"]) is not None
    assert entry["s"] == "mc"
    assert entry["a"] == "c"
    assert entry["r"] == "other"
    assert entry["v"] == {"s": 80.0, "c": 12.5}
    assert entry["m"] == {"g": 3.2, "n": 1.4, "q": 5.6}
    assert entry["w"] == [["cr", 6, "nb_e", 13, "db_s", False]]


def test_history_prefers_effective_needed_reserve() -> None:
    """History records the reserve used to derive the no-action target SOC."""
    sensor = _history_sensor()

    sensor.add_entry(
        "Morning Grid Charge",
        {
            "result": "No action needed",
            "needed_reserve_kwh": 0.5,
            "needed_reserve_sufficiency_kwh": 1.2,
            "needed_reserve_all_kwh": 1.2,
        },
        action_type="no_action",
        reason="Gap 0.0 kWh, gap sufficiency -0.1 kWh",
    )

    entry = sensor.extra_state_attributes["history"][0]

    assert entry["m"] == {"n": 1.2}


def test_history_stores_export_power_in_kw() -> None:
    """History stores compact export setpoints in kW rather than W."""
    sensor = _history_sensor()

    sensor.add_entry(
        "Morning Peak Sell",
        {"result": "Sell", "target_soc": 52.0, "export_power_w": 10200.0},
        action_type="sell",
        reason="Eligible surplus",
    )

    entry = sensor.extra_state_attributes["history"][0]

    assert entry["v"] == {"s": 52.0, "e": 10.2}


def test_equal_hour_history_window_has_zero_duration_on_same_day() -> None:
    """Do not serialize a zero-length decision horizon as tomorrow."""
    outcome = DecisionOutcome(
        scenario="Morning Peak Sell",
        action_type="no_action",
        summary="No action",
        reason="Test",
        details={},
    )

    BaseSellStrategy._apply_history_window(
        outcome,
        start_hour=7,
        end_hour=7,
        end_kind="pv_s",
    )

    assert outcome.history_windows == [["sr", 7, "next_h", 7, "pv_s", False]]
    assert outcome.details["window_end_day_offset"] == 0
    assert outcome.details["window_duration_hours"] == 0
    assert outcome.details["window_hours"] == []


def test_history_discards_entries_older_than_fourteen_days() -> None:
    """History removes expired compact and legacy entries."""
    now = dt_util.now()
    history = [
        {"t": (now - timedelta(days=15)).isoformat(), "s": "mc"},
        {"timestamp": (now - timedelta(days=15)).isoformat(), "scenario": "legacy"},
        {"t": (now - timedelta(days=13, hours=23)).isoformat(), "s": "ac"},
    ]

    trimmed = OptimizationHistorySensor._trim_history(history)

    assert trimmed == [{"t": (now - timedelta(days=13, hours=23)).isoformat(), "s": "ac"}]


def test_history_removes_oldest_entries_to_fit_byte_budget() -> None:
    """History remains below the Home Assistant-safe 14 KiB budget."""
    now = dt_util.now().isoformat()
    history = [
        {
            "t": now,
            "s": "es",
            "a": "s",
            "r": "arbitrage",
            "w": [["sr", 18, "next_h", 4, "arb_b", True]],
            "m": {"x": 1.2, "q": 3.4, "p": 0.8, "b": 0.2, "m": 0.6},
        }
        for _ in range(200)
    ]

    trimmed = OptimizationHistorySensor._trim_history(history)

    assert trimmed
    assert len(trimmed) < len(history)
    assert OptimizationHistorySensor._history_size(trimmed) <= _HISTORY_MAX_BYTES
