"""Morning Charge Completion returns each program to its Normal SOC Target."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import ANY, AsyncMock

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
import pytest

from custom_components.energy_optimizer.const import (
    CONF_GRID_CHARGE_CURRENT_ENTITY,
    CONF_MIN_SOC,
    DOMAIN,
)
from custom_components.energy_optimizer.service_handlers import charge_completion
from tests.test_charge_completion import _Store, _audit, _entry, _hass

pytestmark = pytest.mark.enable_socket

CONFIG = {
    CONF_GRID_CHARGE_CURRENT_ENTITY: "number.grid_charge_current",
    CONF_MIN_SOC: 15,
}


def _plan_store(programs: dict[str, float]) -> _Store:
    now = dt_util.now()
    return _Store(
        {
            "charge_type": "morning",
            "complete_at": now.isoformat(),
            "window_start": (now - timedelta(hours=5)).isoformat(),
            "window_end": now.isoformat(),
            "programs": [
                {"entity_id": entity_id, "soc": soc}
                for entity_id, soc in programs.items()
            ],
        }
    )


@pytest.fixture
def completion(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {
        "set_soc": AsyncMock(),
        "set_current": AsyncMock(),
        "log": AsyncMock(),
        "reschedule": AsyncMock(),
    }
    monkeypatch.setattr(charge_completion, "set_program_soc", mocks["set_soc"])
    monkeypatch.setattr(charge_completion, "set_charge_current", mocks["set_current"])
    monkeypatch.setattr(charge_completion, "log_decision_unified", mocks["log"])
    monkeypatch.setattr(charge_completion, "active_decision_audit", _audit)
    monkeypatch.setattr(
        charge_completion, "async_schedule_charge_completion", mocks["reschedule"]
    )
    return mocks


def _use(monkeypatch: pytest.MonkeyPatch, store: _Store) -> None:
    monkeypatch.setattr(charge_completion, "_store", lambda *_args: store)


@pytest.mark.asyncio
async def test_each_program_returns_to_its_own_normal_soc_target(
    monkeypatch: pytest.MonkeyPatch, completion: dict[str, AsyncMock]
) -> None:
    store = _plan_store({"number.p6_soc": 20, "number.p1_soc": 15, "number.p2_soc": 11})
    _use(monkeypatch, store)
    hass = _hass({"number.p6_soc": "70", "number.p1_soc": "70", "number.p2_soc": "70"})

    await charge_completion.async_handle_charge_completion(
        hass, _entry(CONFIG), "morning"
    )

    completion["set_current"].assert_awaited_once()
    written = [(c.args[1], c.args[2]) for c in completion["set_soc"].await_args_list]
    assert written == [
        ("number.p6_soc", 20.0),
        ("number.p1_soc", 15.0),
        ("number.p2_soc", 11.0),
    ]
    outcome = completion["log"].await_args.args[2]
    assert outcome.action_type == "charge_completed"
    assert store.removed is True


@pytest.mark.asyncio
async def test_program_already_at_its_normal_target_is_not_written(
    monkeypatch: pytest.MonkeyPatch, completion: dict[str, AsyncMock]
) -> None:
    store = _plan_store({"number.p6_soc": 20, "number.p1_soc": 15})
    _use(monkeypatch, store)
    hass = _hass({"number.p6_soc": "20", "number.p1_soc": "70"})

    await charge_completion.async_handle_charge_completion(
        hass, _entry(CONFIG), "morning"
    )

    written = [c.args[1] for c in completion["set_soc"].await_args_list]
    assert written == ["number.p1_soc"]


@pytest.mark.asyncio
async def test_every_program_at_normal_target_is_no_action(
    monkeypatch: pytest.MonkeyPatch, completion: dict[str, AsyncMock]
) -> None:
    store = _plan_store({"number.p6_soc": 20, "number.p1_soc": 15})
    _use(monkeypatch, store)
    hass = _hass({"number.p6_soc": "20", "number.p1_soc": "15"})

    await charge_completion.async_handle_charge_completion(
        hass, _entry(CONFIG), "morning"
    )

    completion["set_soc"].assert_not_awaited()
    completion["set_current"].assert_not_awaited()
    assert completion["log"].await_args.args[2].action_type == "no_action"
    assert store.removed is True


@pytest.mark.asyncio
async def test_failed_program_is_retried_alone_without_rolling_back_the_others(
    monkeypatch: pytest.MonkeyPatch, completion: dict[str, AsyncMock]
) -> None:
    store = _plan_store({"number.p6_soc": 20, "number.p1_soc": 15, "number.p2_soc": 11})
    _use(monkeypatch, store)
    hass = _hass({"number.p6_soc": "70", "number.p1_soc": "70", "number.p2_soc": "70"})
    now = dt_util.now()
    monkeypatch.setattr(charge_completion.dt_util, "now", lambda: now)

    async def _set_soc(_hass, entity_id, value, **_kwargs):
        if entity_id == "number.p1_soc":
            raise HomeAssistantError("write failed")

    completion["set_soc"].side_effect = _set_soc

    await charge_completion.async_handle_charge_completion(
        hass, _entry(CONFIG), "morning"
    )

    assert [c.args[1] for c in completion["set_soc"].await_args_list] == [
        "number.p6_soc",
        "number.p1_soc",
        "number.p2_soc",
    ]
    kwargs = completion["reschedule"].await_args.kwargs
    assert kwargs["restore_targets"] == {"number.p1_soc": 15.0}
    assert kwargs["complete_at"] == now + timedelta(minutes=5)
    assert completion["log"].await_args.args[2].action_type == "charge_completion_failed"
    assert store.removed is False


@pytest.mark.asyncio
async def test_unreadable_program_is_retried_while_the_others_are_restored(
    monkeypatch: pytest.MonkeyPatch, completion: dict[str, AsyncMock]
) -> None:
    store = _plan_store({"number.p6_soc": 20, "number.p1_soc": 15})
    _use(monkeypatch, store)
    hass = _hass({"number.p6_soc": "70", "number.p1_soc": "unavailable"})

    await charge_completion.async_handle_charge_completion(
        hass, _entry(CONFIG), "morning"
    )

    assert [c.args[1] for c in completion["set_soc"].await_args_list] == [
        "number.p6_soc"
    ]
    assert completion["reschedule"].await_args.kwargs["restore_targets"] == {
        "number.p1_soc": 15.0
    }


@pytest.mark.asyncio
async def test_current_write_failure_keeps_every_program_for_the_retry(
    monkeypatch: pytest.MonkeyPatch, completion: dict[str, AsyncMock]
) -> None:
    store = _plan_store({"number.p6_soc": 20, "number.p1_soc": 15})
    _use(monkeypatch, store)
    hass = _hass({"number.p6_soc": "70", "number.p1_soc": "70"})
    completion["set_current"].side_effect = HomeAssistantError("current failed")

    await charge_completion.async_handle_charge_completion(
        hass, _entry(CONFIG), "morning"
    )

    completion["set_soc"].assert_not_awaited()
    assert completion["reschedule"].await_args.kwargs["restore_targets"] == {
        "number.p6_soc": 20.0,
        "number.p1_soc": 15.0,
    }


@pytest.mark.asyncio
async def test_schedule_persists_the_restore_targets_in_the_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store()
    hass = _hass({})
    monkeypatch.setattr(charge_completion, "_store", lambda *_args: store)
    monkeypatch.setattr(
        charge_completion, "async_track_point_in_time", lambda *_a: (lambda: None)
    )
    end = dt_util.now() + timedelta(hours=3)

    await charge_completion.async_schedule_charge_completion(
        hass,
        _entry({}),
        charge_type="morning",
        complete_at=end,
        window_start=end - timedelta(hours=5),
        window_end=end,
        restore_targets={"number.p6_soc": 20.0, "number.p1_soc": 15.0},
    )

    assert store.saved["programs"] == [
        {"entity_id": "number.p6_soc", "soc": 20.0},
        {"entity_id": "number.p1_soc", "soc": 15.0},
    ]
    assert charge_completion.plan_restore_targets(store.saved) == {
        "number.p6_soc": 20.0,
        "number.p1_soc": 15.0,
    }


@pytest.mark.asyncio
async def test_restore_after_restart_keeps_the_restore_targets(
    monkeypatch: pytest.MonkeyPatch, completion: dict[str, AsyncMock]
) -> None:
    now = dt_util.now()
    end = now + timedelta(hours=2)
    store = _Store(
        {
            "charge_type": "morning",
            "complete_at": end.isoformat(),
            "window_start": (end - timedelta(hours=5)).isoformat(),
            "window_end": end.isoformat(),
            "programs": [{"entity_id": "number.p6_soc", "soc": 20.0}],
        }
    )
    monkeypatch.setattr(charge_completion, "_store", lambda *_args: store)

    await charge_completion.async_restore_charge_completions(_hass({}), _entry({}))

    assert completion["reschedule"].await_args.kwargs["restore_targets"] == {
        "number.p6_soc": 20.0
    }


@pytest.mark.asyncio
async def test_completion_waits_for_a_running_morning_charge(
    monkeypatch: pytest.MonkeyPatch, completion: dict[str, AsyncMock]
) -> None:
    """Completion never restores while Morning Charge is mid-transaction."""
    import asyncio

    store = _plan_store({"number.p6_soc": 20})
    _use(monkeypatch, store)
    hass = _hass({"number.p6_soc": "70"})
    entry = _entry(CONFIG)

    async with charge_completion.morning_charge_lock(hass, entry):
        task = asyncio.ensure_future(
            charge_completion.async_handle_charge_completion(hass, entry, "morning")
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        completion["set_soc"].assert_not_awaited()

    await task
    completion["set_soc"].assert_awaited_once()


def _strategy_with_written_p6(hass, entry):
    """A Morning Charge strategy that has just written P6 from 70 to 80."""
    from custom_components.energy_optimizer.decision_engine.morning_charge import (
        MorningChargeStrategy,
        _ProgramTarget,
    )
    from custom_components.energy_optimizer.decision_engine.common import BatteryConfig
    from custom_components.energy_optimizer.market_windows import default_market_windows

    strategy = MorningChargeStrategy(hass, entry_id=entry.entry_id, margin=None)
    strategy.entry = entry
    strategy.bc = BatteryConfig(100, 50, 15, 15, 100, 100)
    p6 = _ProgramTarget(6, "number.p6_soc", 70.0)
    strategy._program_set = (p6,)
    strategy._written_programs = (p6,)
    start = dt_util.now().replace(hour=23, minute=0, second=0, microsecond=0)
    strategy._resolve_completion_window = lambda: (start, start + timedelta(hours=5))
    strategy.windows = default_market_windows(start)
    return strategy


@pytest.mark.asyncio
async def test_baseline_persisted_before_a_restart_is_not_overwritten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run before recovery repopulates the cache still keeps the stored 20 %."""
    store = _plan_store({"number.p6_soc": 20})
    _use(monkeypatch, store)
    schedule = AsyncMock()
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.async_schedule_charge_completion",
        schedule,
    )
    entry = _entry(CONFIG)
    strategy = _strategy_with_written_p6(_hass({}), entry)

    await strategy._schedule_completion(80)

    assert schedule.await_args.kwargs["restore_targets"] == {"number.p6_soc": 20.0}


@pytest.mark.asyncio
async def test_unresolved_baseline_from_an_older_window_is_carried_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P6 20 % that never restored is not replaced by the next night's 70 %."""
    hass = _hass({})
    old_plan = _plan_store({"number.p6_soc": 20}).data
    old_plan["window_end"] = (dt_util.now() - timedelta(days=1)).isoformat()
    hass.data[DOMAIN]["entry-1"]["charge_completion_plans"] = {"morning": old_plan}
    monkeypatch.setattr(charge_completion, "_store", lambda *_args: _Store(old_plan))
    schedule = AsyncMock()
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.morning_charge.async_schedule_charge_completion",
        schedule,
    )
    strategy = _strategy_with_written_p6(hass, _entry(CONFIG))

    await strategy._schedule_completion(80)

    assert schedule.await_args.kwargs["restore_targets"] == {"number.p6_soc": 20.0}


@pytest.mark.asyncio
async def test_recovery_waits_for_a_running_morning_charge(
    monkeypatch: pytest.MonkeyPatch, completion: dict[str, AsyncMock]
) -> None:
    """Startup recovery never reschedules a plan while Morning Charge is writing."""
    import asyncio

    end = dt_util.now() + timedelta(hours=2)
    store = _Store(
        {
            "charge_type": "morning",
            "complete_at": end.isoformat(),
            "window_start": (end - timedelta(hours=5)).isoformat(),
            "window_end": end.isoformat(),
            "programs": [{"entity_id": "number.p6_soc", "soc": 20.0}],
        }
    )
    monkeypatch.setattr(
        charge_completion,
        "_store",
        lambda _hass, _entry, charge_type: store if charge_type == "morning" else _Store(),
    )
    hass = _hass({})
    entry = _entry({})

    async with charge_completion.morning_charge_lock(hass, entry):
        task = asyncio.ensure_future(
            charge_completion.async_restore_charge_completions(hass, entry)
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        completion["reschedule"].assert_not_awaited()

    await task
    completion["reschedule"].assert_awaited_once()
