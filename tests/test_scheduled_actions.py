"""Tests for the scheduled actions diagnostic sensor and scheduler snapshot."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util

from custom_components.energy_optimizer.const import (
    CONF_BEV_CHARGING_BINARY_SENSOR,
    CONF_BUY_PRICE_SENSOR,
    CONF_HIGH_TARIFF_START_HOUR_SENSOR,
    CONF_PROG4_TIME_START_ENTITY,
    CONF_SELL_PRICE_SENSOR,
    DOMAIN,
)
from custom_components.energy_optimizer.entities.sensors.tracking import ScheduledActionsSensor
from custom_components.energy_optimizer.market_windows import (
    MarketWindows,
    MarketWindowSource,
    RankedMarketWindow,
    ResolvedHour,
    ResolvedMarketWindow,
    StaticMarketWindowResolver,
    default_market_windows,
)
from custom_components.energy_optimizer.scheduler.action_scheduler import ActionScheduler
from custom_components.energy_optimizer.sensor import async_setup_entry
from tests.conftest import market_windows


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


_TZ = ZoneInfo("Europe/Warsaw")
_NOW = datetime(2026, 3, 11, 0, 5, tzinfo=_TZ)
_RESCHEDULES = (
        "_schedule_morning_charge",
        "_schedule_afternoon_charge",
        "_schedule_program4_solar_reset",
        "_schedule_morning_sell",
        "_schedule_evening_sell",
        "_schedule_sell_restores",
        "_schedule_daytime_min_price_restore",
    )


def _hour_window(
    hour: int,
    *,
    price: float = 0.5,
    source: MarketWindowSource = MarketWindowSource.PRICES,
    length: int = 1,
) -> ResolvedMarketWindow:
    start = datetime(2026, 3, 11, hour, tzinfo=_TZ)
    return ResolvedMarketWindow(
        start=start,
        end=start + timedelta(hours=length),
        price=price,
        source=source,
    )


def _ranked(
    hour: int, second_hour: int | None = None, **kwargs
) -> RankedMarketWindow:
    return RankedMarketWindow(
        primary=_hour_window(hour, **kwargs),
        secondary=None if second_hour is None else _hour_window(second_hour, **kwargs),
    )


class _SwappableResolver(StaticMarketWindowResolver):
    """Static resolver whose snapshot is swapped between coordinator updates."""

    def swap(self, **changes) -> None:
        self._windows = replace(self._windows, **changes)


def _resolver(**changes) -> _SwappableResolver:
    return _SwappableResolver(replace(default_market_windows(_NOW), **changes))


def _scheduler_with_mocked_reschedules(
    resolver: _SwappableResolver, *, data: dict | None = None
) -> ActionScheduler:
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    scheduler = ActionScheduler(hass, _mock_entry(data=data), MagicMock(), resolver)
    for name in _RESCHEDULES:
        setattr(scheduler, name, MagicMock())
    return scheduler


def _called(scheduler: ActionScheduler) -> set[str]:
    return {name for name in _RESCHEDULES if getattr(scheduler, name).called}


@pytest.mark.asyncio
async def test_sensor_setup_registers_scheduled_actions_sensor() -> None:
    """Sensor platform stores the scheduled actions sensor in hass.data."""
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.data = {"states": {}}
    hass.data = {
        DOMAIN: {
            "entry-1": {
                "coordinator": coordinator,
                "market_windows": StaticMarketWindowResolver(market_windows()),
            }
        }
    }
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
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_point_in_time",
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
        "custom_components.energy_optimizer.scheduler.action_scheduler.dt_util.now",
        lambda: datetime(2026, 3, 11, 0, 5, tzinfo=tz),
    )

    sink = _FakeScheduledActionsSink()
    states = {
        "sun.sun": _sun_state("above_horizon"),
        "sensor.tariff_start": _state("15:00"),
        "sensor.night_buy_window_tomorrow": SimpleNamespace(
            state="22:00-00:00",
            attributes={
                "start_time": "2026-03-11T22:00:00+01:00",
                "end_time": "2026-03-12T00:00:00+01:00",
            },
        ),
        "sensor.morning_peak": _state("07:00"),
        "sensor.evening_peak": _state("18:00"),
        "sensor.evening_peak_2": _state("20:00"),
        "sensor.daytime_min": _state("2026-03-11T12:30:00+01:00"),
        "time.program4_start": _state("09:30"),
    }

    hass = MagicMock()
    hass.states.get.side_effect = states.get
    hass.async_create_task.side_effect = lambda coro: coro.close()
    hass.data = {DOMAIN: {"entry-1": {"scheduled_actions_sensor": sink}}}

    entry = _mock_entry(
        data={
            CONF_SELL_PRICE_SENSOR: "sensor.sell_price",
            CONF_HIGH_TARIFF_START_HOUR_SENSOR: "sensor.tariff_start",
            CONF_PROG4_TIME_START_ENTITY: "time.program4_start",
        }
    )

    try:
        coordinator = MagicMock()
        coordinator.get_morning_charge_start.return_value = datetime(
            2026, 3, 11, 22, 0, tzinfo=tz
        )
        resolver = _resolver(
            night_buy=_hour_window(22, length=2, source=MarketWindowSource.PLAN),
            day_buy=_hour_window(13, length=2, source=MarketWindowSource.PLAN),
            morning_sell=_ranked(7),
            evening_sell=_ranked(18, 20),
            consume=replace(
                _hour_window(12, source=MarketWindowSource.CONFIG_ENTITY),
                start=datetime(2026, 3, 11, 12, 30, tzinfo=_TZ),
                end=datetime(2026, 3, 11, 13, 30, tzinfo=_TZ),
            ),
        )
        scheduler = ActionScheduler(hass, entry, coordinator, resolver)
        scheduler.start()

        assert sink.snapshot is not None
        assert sink.snapshot["date"] == "2026-03-11"
        assert sink.snapshot["timezone"] == "Europe/Warsaw"
        assert sink.snapshot["summary"]["count"] == 12
        assert sink.snapshot["summary"]["fixed_count"] == 1
        assert sink.snapshot["summary"]["dynamic_count"] == 9
        assert sink.snapshot["summary"]["event_driven_count"] == 2
        assert sink.snapshot["next_action"] == {
            "key": "morning_sell",
            "label": "Morning peak sell",
            "time": "2026-03-11T07:00:00+01:00",
        }

        actions = sink.snapshot["actions"]
        assert any(
            action["key"] == "morning_charge"
            and action["time_local"] == "22:00"
            and action["source"] == "plan"
            for action in actions
        )
        assert any(
            action["key"] == "afternoon_charge"
            and action["time_local"] == "13:00"
            and action["source"] == "plan"
            for action in actions
        )
        assert any(
            action["key"] == "program4_solar_reset"
            and action["time_local"] == "09:30"
            and action["source"] == "prog4_time_start_entity"
            for action in actions
        )
        assert any(
            action["key"] == "daytime_min_price_restore"
            and action["time_local"] == "12:30"
            and action["source"] == "config_entity"
            for action in actions
        )
        assert any(
            action["key"] == "evening_sell_second"
            and action["time_local"] == "20:00"
            and action["source"] == "prices"
            for action in actions
        )
        assert any(
            action["key"] == "morning_sell" and action["source"] == "prices"
            for action in actions
        )
        assert any(
            action["key"] == "evening_behavior"
            and action["time_local"] == "21:59"
            for action in actions
        )
        assert any(
            action["key"] == "evening_sell_restore"
            and action["time_local"] == "21:00"
            and action["source"] == "prices"
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

    scheduler = ActionScheduler(hass, entry, resolver=_resolver())
    scheduler._publish_schedule_snapshot()

    assert sink.snapshot is not None
    assert any(
        action["key"] == "solar_charge_block"
        and action["source"] == "sell_price_sensor"
        for action in sink.snapshot["actions"]
    )


def test_start_subscribes_only_to_the_high_tariff_entity_for_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Window changes arrive through the coordinator, not internal sensor events."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    hass.async_create_task.side_effect = lambda coro: coro.close()
    entry = _mock_entry(data={CONF_HIGH_TARIFF_START_HOUR_SENSOR: "sensor.tariff_start"})
    registered_entities: list[tuple[str, ...]] = []

    for name in ("async_track_time_change", "async_track_sunrise", "async_track_sunset"):
        monkeypatch.setattr(
            f"custom_components.energy_optimizer.scheduler.action_scheduler.{name}",
            lambda *args, **kwargs: (lambda: None),
        )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_state_change_event",
        lambda _hass, entities, _callback: registered_entities.append(tuple(entities))
        or (lambda: None),
    )

    scheduler = _scheduler_with_mocked_reschedules(_resolver())
    scheduler.hass = hass
    scheduler.entry = entry
    scheduler._start_price_hourly_listener = MagicMock()
    scheduler._is_sun_above_horizon = MagicMock(return_value=False)
    scheduler._publish_schedule_snapshot = MagicMock()

    scheduler.start()

    assert registered_entities == [("sensor.tariff_start",)]


def test_start_registers_bev_charging_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduler re-evaluates export control when BEV charging changes."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    hass.async_create_task.side_effect = lambda coro: coro.close()
    entry = _mock_entry(
        data={CONF_BEV_CHARGING_BINARY_SENSOR: "binary_sensor.bev_charging"}
    )
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

    scheduler = ActionScheduler(hass, entry)
    scheduler._schedule_morning_charge = MagicMock()
    scheduler._schedule_afternoon_charge = MagicMock()
    scheduler._schedule_morning_sell = MagicMock()
    scheduler._schedule_evening_sell = MagicMock()
    scheduler._schedule_sell_restores = MagicMock()
    scheduler._schedule_daytime_min_price_restore = MagicMock()
    scheduler._is_sun_above_horizon = MagicMock(return_value=False)
    scheduler._publish_schedule_snapshot = MagicMock()

    scheduler.start()

    assert ("binary_sensor.bev_charging",) in registered_entities


@pytest.mark.asyncio
async def test_sunset_restores_export_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sunset restores grid/export and records its diagnostic decision."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    entry = _mock_entry(data={})
    restore = AsyncMock(
        return_value={"reason": "sunset_restore", "action": "normal_operation"}
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_restore_export_block_control",
        restore,
    )

    scheduler = ActionScheduler(hass, entry)
    scheduler._stop_price_hourly_listener = MagicMock()
    scheduler._publish_schedule_snapshot = MagicMock()

    await scheduler._handle_sunset()

    restore.assert_awaited_once_with(
        hass,
        entry_id="entry-1",
        trigger="scheduler:sunset_export_restore",
    )
    assert hass.data[DOMAIN]["entry-1"]["last_export_block_control"] == {
        "reason": "sunset_restore",
        "action": "normal_operation",
    }


def test_schedule_morning_charge_uses_planned_window_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduler should use the internal night buy window start hour."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    entry = _mock_entry(data={})

    captured_times: list[datetime] = []
    coordinator = MagicMock()
    coordinator.get_morning_charge_start.return_value = datetime(2026, 3, 11, 22, 0)
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_point_in_time",
        lambda _hass, _callback, when: captured_times.append(when)
        or (lambda: None),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.dt_util.now",
        lambda: datetime(2026, 3, 11, 12, 0),
    )

    scheduler = ActionScheduler(hass, entry, coordinator)
    scheduler._publish_schedule_snapshot = MagicMock()
    scheduler._schedule_morning_charge()

    assert captured_times == [datetime(2026, 3, 11, 22, 0)]


def test_schedule_afternoon_charge_uses_day_buy_window_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduler should use the snapshot's Day Buy Window start hour."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}
    entry = _mock_entry(data={})

    captured_hours: list[int] = []
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_time_change",
        lambda _hass, _callback, *, hour, minute, second: captured_hours.append(hour)
        or (lambda: None),
    )

    scheduler = ActionScheduler(
        hass, entry, resolver=_resolver(day_buy=_hour_window(11, length=2))
    )
    scheduler._publish_schedule_snapshot = MagicMock()
    scheduler._schedule_afternoon_charge()

    assert captured_hours == [11]


def test_schedule_afternoon_charge_is_skipped_without_a_day_buy_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Day Buy Window for today means no afternoon listener at fallback hours."""
    hass = MagicMock()
    entry = _mock_entry(data={})
    hass.data = {DOMAIN: {"entry-1": {}}}

    captured_hours: list[int] = []
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_time_change",
        lambda _hass, _callback, *, hour, minute, second: captured_hours.append(hour)
        or (lambda: None),
    )

    scheduler = ActionScheduler(hass, entry, resolver=_resolver())
    scheduler._publish_schedule_snapshot = MagicMock()
    scheduler._schedule_afternoon_charge()

    assert captured_hours == []
    assert scheduler._afternoon_listener is None
    scheduler._publish_schedule_snapshot.assert_called_once()


def test_coordinator_update_restores_afternoon_charge_once_a_day_plan_exists() -> None:
    """A plan created after startup changes day_buy and restores the listener."""
    resolver = _resolver()
    scheduler = _scheduler_with_mocked_reschedules(resolver)

    resolver.swap(day_buy=_hour_window(13, length=2, source=MarketWindowSource.PLAN))
    scheduler._handle_coordinator_update()

    scheduler._schedule_afternoon_charge.assert_called_once()
    scheduler._schedule_program4_solar_reset.assert_called_once()


def test_schedule_snapshot_lists_afternoon_charge_only_with_a_day_buy_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The snapshot advertises no afternoon charge while today has no Day Buy Window."""
    hass = MagicMock()
    hass.states.get.return_value = None
    entry = _mock_entry(data={})
    sink = _FakeScheduledActionsSink()
    hass.data = {DOMAIN: {"entry-1": {"scheduled_actions_sensor": sink}}}
    coordinator = MagicMock()
    coordinator.get_morning_charge_start.return_value = None
    scheduler = ActionScheduler(hass, entry, coordinator, _resolver())

    scheduler._publish_schedule_snapshot()

    assert sink.snapshot is not None
    assert all(action["key"] != "afternoon_charge" for action in sink.snapshot["actions"])

    planned = ActionScheduler(
        hass,
        entry,
        coordinator,
        _resolver(day_buy=_hour_window(13, length=2, source=MarketWindowSource.PLAN)),
    )

    planned._publish_schedule_snapshot()

    assert any(
        action["key"] == "afternoon_charge" and action["time_local"] == "13:00"
        for action in sink.snapshot["actions"]
    )


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

    export_mock.assert_awaited_once_with(
        hass,
        entry_id="entry-1",
        trigger="scheduler:price_change_export_block_control",
    )
    solar_mock.assert_awaited_once_with(
        hass,
        entry_id="entry-1",
        trigger="scheduler:price_change_solar_charge_block",
    )
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

    scheduler = ActionScheduler(hass, entry, resolver=_resolver())
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
        data={}
    )
    scheduler = ActionScheduler(
        hass, entry, resolver=_resolver(evening_sell=_ranked(19, 18))
    )
    scheduler._publish_schedule_snapshot = MagicMock()

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


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {"night_buy": _hour_window(23, length=2)},
            {"_schedule_morning_charge"},
        ),
        (
            {"day_buy": _hour_window(12, length=2)},
            {
                "_schedule_morning_charge",
                "_schedule_afternoon_charge",
                "_schedule_program4_solar_reset",
            },
        ),
        (
            {"morning_sell": _ranked(8)},
            {
                "_schedule_morning_charge",
                "_schedule_morning_sell",
                "_schedule_sell_restores",
            },
        ),
        (
            {"evening_sell": _ranked(18, 20)},
            {
                "_schedule_morning_charge",
                "_schedule_evening_sell",
                "_schedule_sell_restores",
            },
        ),
        (
            {"consume": _hour_window(11)},
            {"_schedule_morning_charge", "_schedule_daytime_min_price_restore"},
        ),
        (
            {"high_tariff_start": ResolvedHour(16, MarketWindowSource.CONFIG_ENTITY)},
            {
                "_schedule_morning_charge",
                "_schedule_afternoon_charge",
                "_schedule_program4_solar_reset",
            },
        ),
    ],
)
def test_coordinator_update_reschedules_only_changed_windows(
    changes: dict, expected: set[str]
) -> None:
    """Each changed window reschedules its mapped actions; Morning Charge always."""
    resolver = _resolver()
    scheduler = _scheduler_with_mocked_reschedules(resolver)

    resolver.swap(**changes)
    scheduler._handle_coordinator_update()

    assert _called(scheduler) == expected


def test_coordinator_update_with_identical_windows_reschedules_only_morning_charge() -> None:
    """An unchanged snapshot leaves every window-driven action alone."""
    scheduler = _scheduler_with_mocked_reschedules(_resolver())

    scheduler._handle_coordinator_update()

    assert _called(scheduler) == {"_schedule_morning_charge"}


def test_coordinator_update_stores_the_new_snapshot_before_rescheduling() -> None:
    """The reschedule callbacks read the snapshot that caused them."""
    resolver = _resolver()
    scheduler = _scheduler_with_mocked_reschedules(resolver)
    seen: list[RankedMarketWindow] = []
    scheduler._schedule_evening_sell = lambda: seen.append(scheduler._windows.evening_sell)

    resolver.swap(evening_sell=_ranked(19))
    scheduler._handle_coordinator_update()
    scheduler._handle_coordinator_update()

    assert [window.primary.hour for window in seen] == [19]


@pytest.mark.asyncio
async def test_tariff_entity_change_reschedules_through_the_same_path() -> None:
    """A High-Tariff change takes a fresh snapshot and reschedules what changed."""
    resolver = _resolver()
    scheduler = _scheduler_with_mocked_reschedules(resolver)

    resolver.swap(
        high_tariff_start=ResolvedHour(16, MarketWindowSource.CONFIG_ENTITY),
        day_buy=_hour_window(14, length=2),
    )
    await scheduler._handle_tariff_start_change(MagicMock())

    assert {"_schedule_afternoon_charge", "_schedule_program4_solar_reset"} <= _called(
        scheduler
    )
    assert "_schedule_evening_sell" not in _called(scheduler)

    scheduler._schedule_afternoon_charge.reset_mock()
    scheduler._handle_coordinator_update()
    scheduler._schedule_afternoon_charge.assert_not_called()


@pytest.mark.asyncio
async def test_window_changes_during_completion_restore_apply_once_it_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A coordinator update dropped during restoration is not lost."""
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_restore_charge_completions",
        AsyncMock(),
    )
    resolver = _resolver()
    scheduler = _scheduler_with_mocked_reschedules(resolver)

    resolver.swap(evening_sell=_ranked(19))
    await scheduler._restore_completions_then_schedule_morning_charge()

    assert _called(scheduler) == {
        "_schedule_morning_charge",
        "_schedule_evening_sell",
        "_schedule_sell_restores",
    }


def test_pending_completion_keeps_its_own_source_label() -> None:
    """A completion's window is persisted, so the current window's source is not its source."""
    sink = _FakeScheduledActionsSink()
    scheduler = ActionScheduler(
        MagicMock(), _mock_entry(), MagicMock(), _resolver()
    )
    scheduler.hass.data = {
        DOMAIN: {
            "entry-1": {
                "scheduled_actions_sensor": sink,
                "charge_completion_plans": {
                    "morning": {"complete_at": "2026-03-11T06:00:00+01:00"}
                },
            }
        }
    }
    scheduler.coordinator.get_morning_charge_start.return_value = None

    scheduler._publish_schedule_snapshot()

    completion = next(
        a for a in sink.snapshot["actions"] if a["key"] == "morning_charge_completion"
    )
    assert completion["source"] == "morning_buy_window_end"


def test_pending_completion_reports_the_source_it_was_planned_from() -> None:
    """A planned completion keeps its source after the night window falls back to a default."""
    sink = _FakeScheduledActionsSink()
    scheduler = ActionScheduler(
        MagicMock(), _mock_entry(), MagicMock(), _resolver()
    )
    assert scheduler._windows.night_buy.source.value == "default"
    scheduler.hass.data = {
        DOMAIN: {
            "entry-1": {
                "scheduled_actions_sensor": sink,
                "charge_completion_plans": {
                    "morning": {
                        "complete_at": "2026-03-11T06:00:00+01:00",
                        "window_source": "plan",
                    }
                },
            }
        }
    }
    scheduler.coordinator.get_morning_charge_start.return_value = None

    scheduler._publish_schedule_snapshot()

    completion = next(
        a for a in sink.snapshot["actions"] if a["key"] == "morning_charge_completion"
    )
    assert completion["source"] == "plan"


@pytest.mark.asyncio
async def test_tariff_change_during_completion_restore_does_not_plan_morning_charge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tariff event waits for the pending restore like a coordinator update does."""
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_restore_charge_completions",
        AsyncMock(),
    )
    resolver = _resolver()
    scheduler = _scheduler_with_mocked_reschedules(resolver)
    scheduler._charge_completion_restore_task = MagicMock(done=MagicMock(return_value=False))

    resolver.swap(night_buy=_hour_window(23, length=6))
    await scheduler._handle_tariff_start_change(MagicMock())

    assert _called(scheduler) == set()

    await scheduler._restore_completions_then_schedule_morning_charge()

    assert "_schedule_morning_charge" in _called(scheduler)
