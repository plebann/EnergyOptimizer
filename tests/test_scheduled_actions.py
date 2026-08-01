"""Tests for the scheduled actions diagnostic sensor and scheduler snapshot."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util

from custom_components.energy_optimizer.const import (
    CONF_BUY_PRICE_SENSOR,
    CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR,
    CONF_EVENING_MAX_PRICE_HOUR_SENSOR,
    CONF_EVENING_SECOND_MAX_PRICE_HOUR_SENSOR,
    CONF_MORNING_MAX_PRICE_HOUR_SENSOR,
    CONF_HIGH_TARIFF_START_HOUR_SENSOR,
    CONF_SELL_PRICE_SENSOR,
    DOMAIN,
)
from custom_components.energy_optimizer.entities.sensors.tracking import ScheduledActionsSensor
from custom_components.energy_optimizer.scheduler.action_scheduler import ActionScheduler
from custom_components.energy_optimizer.sensor import async_setup_entry


class _FakeScheduledActionsSink:
    """Simple sink for schedule snapshots."""

    def __init__(self) -> None:
        self.snapshot: dict | None = None
        self.cleared = False

    def update_schedule(self, snapshot: dict) -> None:
        """Store the latest snapshot."""
        self.snapshot = snapshot

    def clear_schedule(self) -> None:
        """Mark the snapshot as cleared."""
        self.cleared = True
        self.snapshot = None


def _mock_entry(*, data: dict | None = None) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = data or {}
    entry.options = {}
    return entry


def _state(state: str) -> SimpleNamespace:
    return SimpleNamespace(state=state)


def _sun_state(state: str) -> SimpleNamespace:
    return SimpleNamespace(state=state, attributes={})


@pytest.mark.asyncio
async def test_sensor_setup_registers_scheduled_actions_sensor() -> None:
    """Sensor platform stores the scheduled actions sensor in hass.data."""
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.data = {"states": {}}
    hass.data = {DOMAIN: {"entry-1": {"coordinator": coordinator}}}
    entry = _mock_entry(data={})
    added_entities: list[object] = []

    def _add_entities(entities: list[object]) -> None:
        added_entities.extend(entities)

    await async_setup_entry(hass, entry, _add_entities)

    assert any(isinstance(entity, ScheduledActionsSensor) for entity in added_entities)
    assert "scheduled_actions_sensor" in hass.data[DOMAIN][entry.entry_id]


def test_scheduled_actions_sensor_updates_native_value_and_attributes() -> None:
    """The sensor stores schedule snapshots in attributes and count in state."""
    coordinator = MagicMock()
    coordinator.data = {"states": {}}
    sensor = ScheduledActionsSensor(coordinator, _mock_entry(), {})
    sensor.async_write_ha_state = MagicMock()

    snapshot = {
        "date": "2026-03-11",
        "timezone": "Europe/Warsaw",
        "generated_at": "2026-03-11T00:05:00+01:00",
        "next_action": {
            "key": "morning_charge",
            "label": "Morning grid charge",
            "time": "2026-03-11T02:00:00+01:00",
        },
        "actions": [
            {"key": "morning_charge"},
            {"key": "afternoon_charge"},
            {"key": "export_block_control", "kind": "event_driven"},
        ],
        "summary": {
            "count": 3,
            "fixed_count": 1,
            "dynamic_count": 1,
            "event_driven_count": 1,
        },
    }

    sensor.update_schedule(snapshot)

    assert sensor.native_value == 3
    assert sensor.extra_state_attributes == snapshot
    sensor.async_write_ha_state.assert_called_once()


def test_scheduler_publishes_structured_daily_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduler publishes today's action plan to the dedicated sensor."""
    tz = ZoneInfo("Europe/Warsaw")
    original_tz = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(tz)

    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_time_change",
        lambda *args, **kwargs: (lambda: None),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_state_change_event",
        lambda *args, **kwargs: (lambda: None),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_sunrise",
        lambda *args, **kwargs: (lambda: None),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_sunset",
        lambda *args, **kwargs: (lambda: None),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.get_internal_sensor_entity_id",
        lambda _hass, *, entry_id, unique_id_suffix, entity_domain="sensor": {
            "night_buy_window": "sensor.night_buy_window",
            "morning_sell_window": "sensor.morning_peak",
            "evening_sell_window": "sensor.evening_peak",
            "midday_sell_window": "sensor.daytime_min",
        }.get(unique_id_suffix),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.helpers.get_internal_sensor_entity_id",
        lambda _hass, *, entry_id, unique_id_suffix, entity_domain="sensor": {
            "night_buy_window": "sensor.night_buy_window",
        }.get(unique_id_suffix),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.dt_util.now",
        lambda: datetime(2026, 3, 11, 0, 5, tzinfo=tz),
    )

    sink = _FakeScheduledActionsSink()
    states = {
        "sun.sun": _sun_state("above_horizon"),
        "sensor.tariff_start": _state("15:00"),
        "sensor.night_buy_window": _state("02:00"),
        "sensor.morning_peak": _state("07:00"),
        "sensor.evening_peak": _state("18:00"),
        "sensor.evening_peak_2": _state("20:00"),
        "sensor.daytime_min": _state("2026-03-11T12:30:00+01:00"),
    }

    hass = MagicMock()
    hass.states.get.side_effect = states.get
    hass.async_create_task.side_effect = lambda coro: coro.close()
    hass.data = {DOMAIN: {"entry-1": {"scheduled_actions_sensor": sink}}}

    entry = _mock_entry(
        data={
            CONF_SELL_PRICE_SENSOR: "sensor.sell_price",
            CONF_HIGH_TARIFF_START_HOUR_SENSOR: "sensor.tariff_start",
            CONF_MORNING_MAX_PRICE_HOUR_SENSOR: "sensor.morning_peak",
            CONF_EVENING_MAX_PRICE_HOUR_SENSOR: "sensor.evening_peak",
            CONF_EVENING_SECOND_MAX_PRICE_HOUR_SENSOR: "sensor.evening_peak_2",
            CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR: "sensor.daytime_min",
        }
    )

    try:
        scheduler = ActionScheduler(hass, entry)
        scheduler.start()

        assert sink.snapshot is not None
        assert sink.snapshot["date"] == "2026-03-11"
        assert sink.snapshot["timezone"] == "Europe/Warsaw"
        assert sink.snapshot["summary"]["count"] == 11
        assert sink.snapshot["summary"]["fixed_count"] == 1
        assert sink.snapshot["summary"]["dynamic_count"] == 8
        assert sink.snapshot["summary"]["event_driven_count"] == 2
        assert sink.snapshot["next_action"] == {
            "key": "morning_charge",
            "label": "Morning grid charge",
            "time": "2026-03-11T02:00:00+01:00",
        }

        actions = sink.snapshot["actions"]
        assert any(
            action["key"] == "morning_charge"
            and action["time_local"] == "02:00"
            and action["source"] == "night_buy_window_sensor"
            for action in actions
        )
        assert any(
            action["key"] == "afternoon_charge"
            and action["time_local"] == "13:00"
            and action["source"] == "high_tariff_start_hour_sensor_minus_2h"
            for action in actions
        )
        assert any(action["key"] == "daytime_min_price_restore" and action["time_local"] == "12:30" for action in actions)
        assert any(action["key"] == "evening_sell_second" and action["time_local"] == "20:00" for action in actions)
        assert any(
            action["key"] == "evening_sell_restore"
            and action["time_local"] == "21:00"
            and action["source"] == "evening_second_max_price_hour_sensor_plus_1h"
            for action in actions
        )
        assert any(
            action["key"] == "solar_charge_block"
            and action["kind"] == "event_driven"
            and action["trigger"] == "hourly_between_sunrise_and_sunset"
            and action["source"] == "sell_price_sensor"
            and action["time"] is None
            for action in actions
        )
        assert any(
            action["key"] == "export_block_control"
            and action["kind"] == "event_driven"
            and action["trigger"] == "hourly_between_sunrise_and_sunset"
            and action["time"] is None
            for action in actions
        )
    finally:
        dt_util.set_default_time_zone(original_tz)


def test_scheduler_describes_solar_charge_block_sell_price_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduled actions should mirror solar charge block's sell-price preference."""
    sink = _FakeScheduledActionsSink()
    hass = MagicMock()
    hass.states.get.return_value = _sun_state("below_horizon")
    hass.async_create_task.side_effect = lambda coro: coro.close()
    hass.data = {DOMAIN: {"entry-1": {"scheduled_actions_sensor": sink}}}
    entry = _mock_entry(
        data={
            CONF_BUY_PRICE_SENSOR: "sensor.buy_price",
            CONF_SELL_PRICE_SENSOR: "sensor.sell_price",
        }
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_night_buy_window_start_hour",
        lambda *args, **kwargs: 2,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_morning_max_price_hour",
        lambda *args, **kwargs: 7,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_tariff_start_hour",
        lambda *args, **kwargs: 15,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_evening_max_price_hour",
        lambda *args, **kwargs: 18,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_evening_second_max_price_hour",
        lambda *args, **kwargs: 20,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_daytime_min_price_time",
        lambda *args, **kwargs: datetime(2026, 3, 11, 12, 30).time(),
    )

    scheduler = ActionScheduler(hass, entry)
    scheduler._publish_schedule_snapshot()

    assert sink.snapshot is not None
    assert any(
        action["key"] == "solar_charge_block"
        and action["source"] == "sell_price_sensor"
        for action in sink.snapshot["actions"]
    )


def test_start_registers_single_evening_sell_window_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduler should only register one listener for the shared evening sell sensor."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    entry = _mock_entry(data={})
    registered_entities: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_time_change",
        lambda *args, **kwargs: (lambda: None),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_sunrise",
        lambda *args, **kwargs: (lambda: None),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_sunset",
        lambda *args, **kwargs: (lambda: None),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_state_change_event",
        lambda _hass, entities, _callback: registered_entities.append(tuple(entities))
        or (lambda: None),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.get_internal_sensor_entity_id",
        lambda _hass, *, entry_id, unique_id_suffix, entity_domain="sensor": (
            f"{entity_domain}.{entry_id}_{unique_id_suffix}"
        ),
    )

    scheduler = ActionScheduler(hass, entry)
    scheduler._schedule_morning_charge = MagicMock()
    scheduler._schedule_afternoon_charge = MagicMock()
    scheduler._schedule_morning_sell = MagicMock()
    scheduler._schedule_evening_sell = MagicMock()
    scheduler._schedule_sell_restores = MagicMock()
    scheduler._schedule_daytime_min_price_restore = MagicMock()
    scheduler._start_price_hourly_listener = MagicMock()
    scheduler._is_sun_above_horizon = MagicMock(return_value=False)
    scheduler._publish_schedule_snapshot = MagicMock()

    scheduler.start()

    assert registered_entities.count(("sensor.entry-1_evening_sell_window",)) == 1


def test_schedule_morning_charge_uses_night_buy_window_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduler should use the internal night buy window start hour."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    entry = _mock_entry(data={})

    captured_hours: list[int] = []
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_night_buy_window_start_hour",
        lambda hass, config, entry_id, default_hour=4: 2,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_time_change",
        lambda _hass, _callback, *, hour, minute, second: captured_hours.append(hour)
        or (lambda: None),
    )

    scheduler = ActionScheduler(hass, entry)
    scheduler._publish_schedule_snapshot = MagicMock()
    scheduler._schedule_morning_charge()

    assert captured_hours == [2]


def test_schedule_morning_charge_falls_back_to_hour_four(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduler should fall back to 04:00 when the window start cannot be resolved."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    entry = _mock_entry(data={})

    captured_hours: list[int] = []
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_night_buy_window_start_hour",
        lambda hass, config, entry_id, default_hour=4: 4,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_time_change",
        lambda _hass, _callback, *, hour, minute, second: captured_hours.append(hour)
        or (lambda: None),
    )

    scheduler = ActionScheduler(hass, entry)
    scheduler._publish_schedule_snapshot = MagicMock()
    scheduler._schedule_morning_charge()

    assert captured_hours == [4]


@pytest.mark.asyncio
async def test_price_hourly_handler_runs_export_and_solar_block_during_daylight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hourly daytime handler should run both export and solar charge block actions."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    hass.states.get.return_value = _sun_state("above_horizon")
    entry = _mock_entry(data={})
    scheduler = ActionScheduler(hass, entry)

    export_mock = AsyncMock()
    solar_mock = AsyncMock()

    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_run_export_block_control",
        export_mock,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_run_solar_charge_block",
        solar_mock,
    )
    scheduler._publish_schedule_snapshot = MagicMock()

    await scheduler._handle_price_hourly(now=datetime(2026, 3, 11, 10, 0, 0))

    export_mock.assert_awaited_once_with(hass, entry_id="entry-1")
    solar_mock.assert_awaited_once_with(hass, entry_id="entry-1")
    scheduler._publish_schedule_snapshot.assert_called_once()


@pytest.mark.asyncio
async def test_price_hourly_handler_skips_outside_daylight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hourly daytime handler should skip when the sun is below horizon."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    hass.states.get.return_value = _sun_state("below_horizon")
    entry = _mock_entry(data={})
    scheduler = ActionScheduler(hass, entry)

    export_mock = AsyncMock()
    solar_mock = AsyncMock()

    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_run_export_block_control",
        export_mock,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_run_solar_charge_block",
        solar_mock,
    )
    scheduler._publish_schedule_snapshot = MagicMock()

    await scheduler._handle_price_hourly(now=datetime(2026, 3, 11, 22, 0, 0))

    export_mock.assert_not_awaited()
    solar_mock.assert_not_awaited()
    scheduler._publish_schedule_snapshot.assert_not_called()


@pytest.mark.asyncio
async def test_sunrise_and_sunset_toggle_hourly_price_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sunrise enables and sunset disables the hourly price-control listener."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    entry = _mock_entry(data={})
    scheduler = ActionScheduler(hass, entry)
    scheduler._publish_schedule_snapshot = MagicMock()

    removed: list[str] = []

    def _fake_track_time_change(*args, **kwargs):
        return lambda: removed.append("hourly")

    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_time_change",
        _fake_track_time_change,
    )

    await scheduler._handle_sunrise()

    assert scheduler._price_hourly_listener is not None

    await scheduler._handle_sunset()

    assert scheduler._price_hourly_listener is None
    assert removed == ["hourly"]
    assert scheduler._publish_schedule_snapshot.call_count == 2


@pytest.mark.asyncio
async def test_start_registers_sunrise_callback_that_runs_without_datetime_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sunrise listener callback registered in start() should work without now arg."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    hass.states.get.return_value = _sun_state("below_horizon")
    hass.async_create_task.side_effect = lambda coro: coro.close()
    entry = _mock_entry(data={})

    captured_sunrise_callback = None

    def _fake_track_sunrise(_hass, callback):
        nonlocal captured_sunrise_callback
        captured_sunrise_callback = callback
        return lambda: None

    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_sunrise",
        _fake_track_sunrise,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_sunset",
        lambda *args, **kwargs: (lambda: None),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_time_change",
        lambda *args, **kwargs: (lambda: None),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_state_change_event",
        lambda *args, **kwargs: (lambda: None),
    )

    scheduler = ActionScheduler(hass, entry)
    scheduler._publish_schedule_snapshot = MagicMock()
    scheduler.start()

    assert captured_sunrise_callback is not None

    await captured_sunrise_callback()

    assert scheduler._price_hourly_listener is not None


@pytest.mark.asyncio
async def test_evening_scheduler_passes_primary_and_first_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evening scheduler should pass A/B metadata without embedding price logic."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    entry = _mock_entry(
        data={
            CONF_EVENING_MAX_PRICE_HOUR_SENSOR: "sensor.evening_peak",
            CONF_EVENING_SECOND_MAX_PRICE_HOUR_SENSOR: "sensor.evening_peak_2",
        }
    )
    scheduler = ActionScheduler(hass, entry)
    scheduler._publish_schedule_snapshot = MagicMock()

    states = {
        "sensor.evening_peak": _state("19:00"),
        "sensor.evening_peak_2": _state("18:00"),
    }
    hass.states.get.side_effect = states.get

    evening_mock = AsyncMock()
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_run_evening_sell",
        evening_mock,
    )

    await scheduler._handle_evening_sell(now=datetime(2026, 3, 11, 19, 0, 0))
    await scheduler._handle_evening_sell_second(now=datetime(2026, 3, 11, 18, 0, 0))

    assert evening_mock.await_args_list[0].kwargs["is_primary"] is True
    assert evening_mock.await_args_list[0].kwargs["is_first"] is False
    assert evening_mock.await_args_list[1].kwargs["is_primary"] is False
    assert evening_mock.await_args_list[1].kwargs["is_first"] is True