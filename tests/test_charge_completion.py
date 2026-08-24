"""Focused tests for temporary charge-target completion."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import ANY, AsyncMock, MagicMock, call

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.energy_optimizer.const import (
    CONF_BATTERY_SOC_SENSOR,
    CONF_MIN_SOC,
    CONF_MIN_SOC_PV,
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG2_TIME_START_ENTITY,
    CONF_PROG4_SOC_ENTITY,
    DOMAIN,
)
from custom_components.energy_optimizer.decision_engine.common import (
    build_no_action_outcome,
    handle_no_action_soc_update,
)
from custom_components.energy_optimizer.decision_engine.morning_charge import (
    MorningChargeStrategy,
)
from custom_components.energy_optimizer.decision_engine.afternoon_charge import (
    AfternoonChargeStrategy,
)
from custom_components.energy_optimizer.decision_engine.common import BatteryConfig
from custom_components.energy_optimizer.service_handlers import charge_completion
from custom_components.energy_optimizer.decision_engine import charge_base

pytestmark = pytest.mark.enable_socket


class _Store:
    """Small async store double."""

    def __init__(self, data=None) -> None:
        self.data = data
        self.saved = None
        self.removed = False

    async def async_load(self):
        return self.data

    async def async_save(self, data) -> None:
        self.data = data
        self.saved = data

    async def async_remove(self) -> None:
        self.data = None
        self.removed = True


def _entry(data: dict[str, object]) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.domain = DOMAIN
    entry.data = data
    return entry


def _hass(states: dict[str, str]) -> MagicMock:
    hass = MagicMock()
    hass.states.get.side_effect = lambda entity_id: (
        MagicMock(state=states[entity_id]) if entity_id in states else None
    )
    hass.data = {DOMAIN: {"entry-1": {}}}
    hass.bus.async_fire = MagicMock()
    return hass


@asynccontextmanager
async def _audit(*_args, **_kwargs):
    yield MagicMock()


@pytest.mark.asyncio
async def test_soc_only_no_action_update_uses_program_soc_updated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real SOC-only write is not reported as no-action."""
    outcome = build_no_action_outcome(
        scenario="Morning Grid Charge",
        reason="reserve sufficient",
        current_soc=80,
        reserve_kwh=1,
        required_kwh=1,
        pv_forecast_kwh=0,
    )
    set_soc = AsyncMock()
    log_outcome = AsyncMock()
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.common.set_program_soc",
        set_soc,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.common.log_decision_unified",
        log_outcome,
    )

    changed = await handle_no_action_soc_update(
        MagicMock(),
        _entry({}),
        integration_context=Context(),
        prog_soc_entity="number.program2_soc",
        current_prog_soc=20,
        target_soc=30,
        outcome=outcome,
    )

    assert changed is True
    assert outcome.action_type == "program_soc_updated"
    assert outcome.entities_changed == [
        {"entity_id": "number.program2_soc", "value": 30}
    ]


@pytest.mark.asyncio
async def test_morning_soc_failure_restores_previous_start_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Program 2 SOC failure rolls the successful time write back."""
    entry = _entry(
        {
            CONF_PROG2_SOC_ENTITY: "number.program2_soc",
            CONF_PROG2_TIME_START_ENTITY: "time.program2_start",
        }
    )
    hass = _hass({"time.program2_start": "03:30:00"})
    strategy = MorningChargeStrategy(hass, entry_id=entry.entry_id, margin=None)
    strategy.entry = entry
    strategy.config = entry.data
    strategy.prog_soc_entity = "number.program2_soc"
    strategy.prog_soc_value = 20
    strategy.integration_context = Context()
    start = dt_util.now().replace(hour=4, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(
        strategy,
        "_resolve_completion_window",
        lambda: (start, start + timedelta(hours=2)),
    )
    set_time = AsyncMock()
    set_soc = AsyncMock(side_effect=HomeAssistantError("SOC write failed"))
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.set_program_start_time",
        set_time,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.set_program_soc",
        set_soc,
    )
    strategy._log_write_failure = AsyncMock()

    changed = await strategy._write_temporary_program_soc(60)

    assert changed is None
    assert set_time.await_args_list == [
        call(
            hass,
            "time.program2_start",
            start.time(),
            entry=entry,
            logger=ANY,
            context=strategy.integration_context,
        ),
        call(
            hass,
            "time.program2_start",
            datetime.strptime("03:30:00", "%H:%M:%S").time(),
            entry=entry,
            logger=ANY,
            context=strategy.integration_context,
        ),
    ]
    strategy._log_write_failure.assert_awaited_once_with("SOC write failed")


@pytest.mark.asyncio
async def test_morning_time_failure_prevents_soc_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Program 2 SOC is not written when its start-time update fails."""
    entry = _entry(
        {
            CONF_PROG2_SOC_ENTITY: "number.program2_soc",
            CONF_PROG2_TIME_START_ENTITY: "time.program2_start",
        }
    )
    hass = _hass({"time.program2_start": "03:30:00"})
    strategy = MorningChargeStrategy(hass, entry_id=entry.entry_id, margin=None)
    strategy.entry = entry
    strategy.config = entry.data
    strategy.prog_soc_entity = "number.program2_soc"
    strategy.prog_soc_value = 20
    strategy.integration_context = Context()
    start = dt_util.now().replace(hour=4, minute=0, second=0, microsecond=0)
    strategy._resolve_completion_window = MagicMock(
        return_value=(start, start + timedelta(hours=2))
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.set_program_start_time",
        AsyncMock(side_effect=HomeAssistantError("time write failed")),
    )
    set_soc = AsyncMock()
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.set_program_soc",
        set_soc,
    )
    strategy._log_write_failure = AsyncMock()

    changed = await strategy._write_temporary_program_soc(60)

    assert changed is None
    set_soc.assert_not_awaited()
    strategy._log_write_failure.assert_awaited_once_with("time write failed")


@pytest.mark.asyncio
async def test_morning_current_failure_restores_program_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A charge-current failure rolls back the already-written Program 2 controls."""
    strategy = MorningChargeStrategy(MagicMock(), entry_id="entry-1", margin=None)
    strategy.entry = _entry({})
    strategy.config = {"charge_current_entity": "number.charge_current"}
    strategy.integration_context = Context()
    strategy._write_temporary_program_soc = AsyncMock(return_value=[])
    strategy._rollback_temporary_program_soc = AsyncMock()
    strategy._log_write_failure = AsyncMock()
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.set_charge_current",
        AsyncMock(side_effect=HomeAssistantError("current write failed")),
    )

    changed = await strategy._apply_charge_action(
        MagicMock(target_soc=60, charge_current=10)
    )

    assert changed is None
    strategy._rollback_temporary_program_soc.assert_awaited_once()
    strategy._log_write_failure.assert_awaited_once_with("current write failed")


@pytest.mark.asyncio
async def test_morning_completion_scheduled_when_target_is_already_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A temporary morning target is reset even without a fresh SOC write."""
    entry = _entry({CONF_PROG2_SOC_ENTITY: "number.program2_soc"})
    hass = _hass({"number.program2_soc": "60"})
    strategy = MorningChargeStrategy(hass, entry_id=entry.entry_id, margin=None)
    strategy.entry = entry
    strategy.config = entry.data
    strategy.bc = BatteryConfig(100, 50, 15, 15, 100, 100)
    start = dt_util.now().replace(hour=4, minute=0, second=0, microsecond=0)
    strategy._resolve_completion_window = MagicMock(
        return_value=(start, start + timedelta(hours=2))
    )
    schedule = AsyncMock()
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.async_schedule_charge_completion",
        schedule,
    )

    await strategy._schedule_completion(60)

    schedule.assert_awaited_once()
    assert schedule.await_args.kwargs["complete_at"] == start + timedelta(hours=2)


@pytest.mark.asyncio
async def test_afternoon_schedules_completion_only_after_program_soc_write() -> None:
    """A charge-current-only afternoon action does not create a completion."""
    strategy = AfternoonChargeStrategy(MagicMock(), entry_id="entry-1", margin=None)
    strategy._schedule_completion = AsyncMock()
    action = MagicMock()

    await strategy._after_charge_action(action, program_soc_changed=False)
    strategy._schedule_completion.assert_not_awaited()

    await strategy._after_charge_action(action, program_soc_changed=True)
    strategy._schedule_completion.assert_awaited_once()


@pytest.mark.asyncio
async def test_afternoon_current_failure_rolls_back_program_soc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A charge-current failure does not leave Program 4 at a temporary target."""
    entry = _entry({})
    strategy = AfternoonChargeStrategy(MagicMock(), entry_id="entry-1", margin=None)
    strategy.entry = entry
    strategy.config = {"charge_current_entity": "number.charge_current"}
    strategy.prog_soc_entity = "number.program4_soc"
    strategy.prog_soc_value = 20
    strategy.integration_context = Context()
    set_soc = AsyncMock()
    monkeypatch.setattr(charge_base, "set_program_soc", set_soc)
    monkeypatch.setattr(
        charge_base,
        "set_charge_current",
        AsyncMock(side_effect=HomeAssistantError("current write failed")),
    )

    changed = await strategy._apply_charge_action(
        MagicMock(target_soc=60, charge_current=10)
    )

    assert changed is None
    assert set_soc.await_args_list == [
        call(
            strategy.hass,
            "number.program4_soc",
            60,
            entry=entry,
            logger=ANY,
            context=strategy.integration_context,
        ),
        call(
            strategy.hass,
            "number.program4_soc",
            20,
            entry=entry,
            logger=ANY,
            context=strategy.integration_context,
        ),
    ]


def test_resolve_charge_window_uses_sensor_start_and_dynamic_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolved completion timing follows the buy-window duration."""
    now = datetime(2026, 8, 24, 1, 0, tzinfo=dt_util.UTC)
    entry = _entry({})
    state = MagicMock(
        state="02:30",
        attributes={"duration_hours": 3.5},
    )
    hass = MagicMock()
    hass.states.get.return_value = state
    monkeypatch.setattr(charge_completion.dt_util, "now", lambda: now)
    monkeypatch.setattr(
        charge_completion,
        "get_internal_sensor_entity_id",
        lambda *_args, **_kwargs: "sensor.night_buy_window",
    )

    start, end = charge_completion.resolve_charge_window(
        hass,
        entry,
        charge_type="morning",
        fallback_start_hour=4,
        fallback_end_hour=6,
    )

    assert start == datetime(2026, 8, 24, 2, 30, tzinfo=dt_util.UTC)
    assert end == datetime(2026, 8, 24, 6, 0, tzinfo=dt_util.UTC)


@pytest.mark.asyncio
async def test_schedule_completion_persists_and_tracks_window_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completion plan is persisted before its point-in-time listener."""
    entry = _entry({})
    hass = _hass({})
    store = _Store()
    tracked: dict[str, object] = {}
    snapshot_callback = MagicMock()
    hass.data[DOMAIN]["entry-1"]["charge_completion_snapshot_callback"] = (
        snapshot_callback
    )
    monkeypatch.setattr(charge_completion, "_store", lambda *_args: store)
    monkeypatch.setattr(
        charge_completion,
        "async_track_point_in_time",
        lambda _hass, callback, when: tracked.update(
            callback=callback,
            when=when,
        )
        or (lambda: None),
    )
    start = datetime(2026, 8, 24, 2, 30, tzinfo=dt_util.UTC)
    end = start + timedelta(hours=3, minutes=30)

    await charge_completion.async_schedule_charge_completion(
        hass,
        entry,
        charge_type="morning",
        complete_at=end,
        window_start=start,
        window_end=end,
    )

    assert store.saved["complete_at"] == end.isoformat()
    assert tracked["when"] == end
    snapshot_callback.assert_called_once()


@pytest.mark.asyncio
async def test_morning_completion_skips_soc_already_at_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Morning completion reports no-action when Program 2 is already minimum."""
    entry = _entry({CONF_PROG2_SOC_ENTITY: "number.program2_soc", CONF_MIN_SOC: 15})
    hass = _hass({"number.program2_soc": "15"})
    store = _Store(
        {
            "charge_type": "morning",
            "complete_at": dt_util.now().isoformat(),
            "window_start": dt_util.now().isoformat(),
            "window_end": dt_util.now().isoformat(),
        }
    )
    set_soc = AsyncMock()
    log_outcome = AsyncMock()
    monkeypatch.setattr(charge_completion, "_store", lambda *_args: store)
    monkeypatch.setattr(charge_completion, "set_program_soc", set_soc)
    monkeypatch.setattr(charge_completion, "log_decision_unified", log_outcome)
    monkeypatch.setattr(charge_completion, "active_decision_audit", _audit)

    await charge_completion.async_handle_charge_completion(hass, entry, "morning")

    set_soc.assert_not_awaited()
    assert store.removed is True
    assert log_outcome.await_args.args[2].action_type == "no_action"


@pytest.mark.asyncio
async def test_afternoon_completion_uses_lower_battery_or_min_soc_pv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Afternoon completion caps Program 4 at current battery SOC."""
    entry = _entry(
        {
            CONF_PROG4_SOC_ENTITY: "number.program4_soc",
            CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
            CONF_MIN_SOC_PV: 15,
        }
    )
    hass = _hass(
        {
            "number.program4_soc": "60",
            "sensor.battery_soc": "10",
        }
    )
    store = _Store(
        {
            "charge_type": "afternoon",
            "complete_at": dt_util.now().isoformat(),
            "window_start": dt_util.now().isoformat(),
            "window_end": dt_util.now().isoformat(),
        }
    )
    set_soc = AsyncMock()
    log_outcome = AsyncMock()
    monkeypatch.setattr(charge_completion, "_store", lambda *_args: store)
    monkeypatch.setattr(charge_completion, "set_program_soc", set_soc)
    monkeypatch.setattr(charge_completion, "log_decision_unified", log_outcome)
    monkeypatch.setattr(charge_completion, "active_decision_audit", _audit)

    await charge_completion.async_handle_charge_completion(
        hass, entry, "afternoon"
    )

    set_soc.assert_awaited_once()
    assert set_soc.await_args.args[2] == 10
    assert store.removed is True
    assert log_outcome.await_args.args[2].action_type == "charge_completed"


@pytest.mark.asyncio
async def test_afternoon_completion_invalid_battery_is_failure_and_clears_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid completion SOC fails explicitly without retaining a retry plan."""
    entry = _entry(
        {
            CONF_PROG4_SOC_ENTITY: "number.program4_soc",
            CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
            CONF_MIN_SOC_PV: 15,
        }
    )
    hass = _hass(
        {
            "number.program4_soc": "60",
            "sensor.battery_soc": "unavailable",
        }
    )
    store = _Store(
        {
            "charge_type": "afternoon",
            "complete_at": dt_util.now().isoformat(),
            "window_start": dt_util.now().isoformat(),
            "window_end": dt_util.now().isoformat(),
        }
    )
    set_soc = AsyncMock()
    log_outcome = AsyncMock()
    monkeypatch.setattr(charge_completion, "_store", lambda *_args: store)
    monkeypatch.setattr(charge_completion, "set_program_soc", set_soc)
    monkeypatch.setattr(charge_completion, "log_decision_unified", log_outcome)
    monkeypatch.setattr(charge_completion, "active_decision_audit", _audit)

    await charge_completion.async_handle_charge_completion(
        hass, entry, "afternoon"
    )

    set_soc.assert_not_awaited()
    assert store.removed is True
    outcome = log_outcome.await_args.args[2]
    assert outcome.action_type == "charge_completion_failed"
    assert outcome.reason == "Battery SOC unavailable or invalid at completion"


@pytest.mark.asyncio
async def test_completion_write_failure_keeps_and_reschedules_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient inverter failure retains the completion plan for retry."""
    entry = _entry({CONF_PROG2_SOC_ENTITY: "number.program2_soc", CONF_MIN_SOC: 15})
    hass = _hass({"number.program2_soc": "60"})
    now = dt_util.now()
    store = _Store(
        {
            "charge_type": "morning",
            "complete_at": now.isoformat(),
            "window_start": (now - timedelta(hours=2)).isoformat(),
            "window_end": now.isoformat(),
        }
    )
    reschedule = AsyncMock()
    monkeypatch.setattr(charge_completion, "_store", lambda *_args: store)
    monkeypatch.setattr(
        charge_completion,
        "set_program_soc",
        AsyncMock(side_effect=HomeAssistantError("inverter unavailable")),
    )
    monkeypatch.setattr(charge_completion, "log_decision_unified", AsyncMock())
    monkeypatch.setattr(charge_completion, "active_decision_audit", _audit)
    monkeypatch.setattr(
        charge_completion,
        "async_schedule_charge_completion",
        reschedule,
    )

    await charge_completion.async_handle_charge_completion(hass, entry, "morning")

    assert store.removed is False
    reschedule.assert_awaited_once()
    assert reschedule.await_args.kwargs["charge_type"] == "morning"


@pytest.mark.asyncio
async def test_program_soc_unavailable_completion_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient Program SOC read failure retains and reschedules the plan."""
    entry = _entry({CONF_PROG2_SOC_ENTITY: "number.program2_soc", CONF_MIN_SOC: 15})
    hass = _hass({})
    now = dt_util.now()
    store = _Store(
        {
            "charge_type": "morning",
            "complete_at": now.isoformat(),
            "window_start": (now - timedelta(hours=2)).isoformat(),
            "window_end": now.isoformat(),
        }
    )
    reschedule = AsyncMock()
    monkeypatch.setattr(charge_completion, "_store", lambda *_args: store)
    monkeypatch.setattr(charge_completion, "log_decision_unified", AsyncMock())
    monkeypatch.setattr(charge_completion, "active_decision_audit", _audit)
    monkeypatch.setattr(
        charge_completion,
        "async_schedule_charge_completion",
        reschedule,
    )

    await charge_completion.async_handle_charge_completion(hass, entry, "morning")

    assert store.removed is False
    reschedule.assert_awaited_once()


@pytest.mark.asyncio
async def test_overdue_completion_runs_during_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup recovery immediately executes an overdue completion."""
    now = dt_util.now()
    entry = _entry({CONF_PROG2_SOC_ENTITY: "number.program2_soc", CONF_MIN_SOC: 15})
    hass = _hass({"number.program2_soc": "60"})
    stores = {
        "morning": _Store(
            {
                "charge_type": "morning",
                "complete_at": (now - timedelta(minutes=1)).isoformat(),
                "window_start": (now - timedelta(hours=2)).isoformat(),
                "window_end": (now - timedelta(minutes=1)).isoformat(),
            }
        ),
        "afternoon": _Store(),
    }
    handle = AsyncMock()
    monkeypatch.setattr(
        charge_completion,
        "_store",
        lambda _hass, _entry, charge_type: stores[charge_type],
    )
    monkeypatch.setattr(charge_completion, "async_handle_charge_completion", handle)
    monkeypatch.setattr(charge_completion.dt_util, "now", lambda: now)

    await charge_completion.async_restore_charge_completions(hass, entry)

    handle.assert_awaited_once_with(hass, entry, "morning")
