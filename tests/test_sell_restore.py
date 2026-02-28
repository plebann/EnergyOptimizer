"""Tests for sell restore persistence and callbacks."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import DOMAIN
from custom_components.energy_optimizer.decision_engine.sell_base import (
    BaseSellStrategy,
    SellRequest,
)
from custom_components.energy_optimizer.scheduler.action_scheduler import ActionScheduler


class _TestSellStrategy(BaseSellStrategy):
    @property
    def scenario_name(self) -> str:
        return "Evening Peak Sell"

    @property
    def sell_type(self) -> str:
        return "evening"

    def _get_prog_soc_state(self) -> tuple[str, float] | None:
        return None

    def _get_price(self) -> float | None:
        return None

    def _resolve_sell_hour(self) -> int:
        return 17

    async def _evaluate_sell(self):
        raise NotImplementedError


class _FakeStore:
    """Simple async Store test double."""

    saved_data: dict | None = None
    load_data: dict | None = None
    removed: bool = False

    def __init__(self, hass, version, key):
        self.hass = hass
        self.version = version
        self.key = key

    async def async_save(self, data: dict) -> None:
        self.__class__.saved_data = data

    async def async_load(self):
        return self.__class__.load_data

    async def async_remove(self) -> None:
        self.__class__.removed = True


@pytest.mark.asyncio
async def test_execute_sell_saves_restore_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Save restore payload after successful sell writes."""
    hass = MagicMock()
    work_mode_state = MagicMock()
    work_mode_state.state = "Zero Export to Load"
    hass.states.get.return_value = work_mode_state
    hass.data = {DOMAIN: {"entry-1": {}}}

    entry = MagicMock()
    entry.entry_id = "entry-1"

    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.sell_base.Store",
        _FakeStore,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.sell_base.set_work_mode",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.sell_base.set_program_soc",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.sell_base.set_export_power",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.sell_base.log_decision_unified",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.sell_base.calculate_export_power",
        lambda _surplus: 1200.0,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.sell_base.is_test_sell_mode",
        lambda _hass, _entry: False,
    )

    _FakeStore.saved_data = None
    _FakeStore.load_data = None
    _FakeStore.removed = False

    outcome = SimpleNamespace(details={}, entities_changed=[])
    strategy = _TestSellStrategy(hass, entry_id="entry-1", margin=1.0)
    strategy.entry = entry
    strategy.config = {
        "work_mode_entity": "select.work_mode",
        "export_power_entity": "number.export_power",
    }
    strategy.battery_config = SimpleNamespace(min_soc=15.0, capacity_ah=37.0, voltage=640.0)
    strategy.current_soc = 90.0
    strategy.prog_soc_entity = "number.prog5_soc"
    strategy.original_prog_soc = 70.0
    strategy.restore_hour = 18
    strategy.integration_context = SimpleNamespace()

    await strategy._execute_sell(
        SellRequest(
            surplus_kwh=3.0,
            build_outcome_fn=lambda _target, _surplus, _export: outcome,
            build_no_action_fn=lambda _surplus: outcome,
        )
    )

    restore = hass.data[DOMAIN]["entry-1"].get("sell_restore")
    assert restore is not None
    assert restore["work_mode"] == "Zero Export to Load"
    assert restore["prog_soc_entity"] == "number.prog5_soc"
    assert restore["prog_soc_value"] == pytest.approx(70.0)
    assert restore["restore_hour"] == 18
    assert restore["sell_type"] == "evening"
    assert _FakeStore.saved_data == restore


@pytest.mark.asyncio
async def test_restore_callback_restores_work_mode_and_soc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restore callback calls inverter writes and clears stored payload."""
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "entry-1": {
                "sell_restore": {
                    "work_mode": "Zero Export to Load",
                    "prog_soc_entity": "number.prog5_soc",
                    "prog_soc_value": 65.0,
                    "restore_hour": 18,
                    "sell_type": "evening",
                    "timestamp": "2026-02-27T17:00:00+00:00",
                }
            }
        }
    }

    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {"work_mode_entity": "select.work_mode"}

    scheduler = ActionScheduler(hass, entry)
    set_work_mode_mock = AsyncMock()
    set_program_soc_mock = AsyncMock()

    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.Store",
        _FakeStore,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.set_work_mode",
        set_work_mode_mock,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.set_program_soc",
        set_program_soc_mock,
    )

    _FakeStore.saved_data = None
    _FakeStore.load_data = None
    _FakeStore.removed = False

    await scheduler._handle_sell_restore("evening", datetime(2026, 2, 27, 18, 0, 0))

    assert set_work_mode_mock.await_count == 1
    assert set_program_soc_mock.await_count == 1
    assert "sell_restore" not in hass.data[DOMAIN]["entry-1"]
    assert _FakeStore.removed is True


@pytest.mark.asyncio
async def test_startup_recovery_restores_immediately_when_overdue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When startup is after restore hour, overdue restore runs immediately."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {}}}

    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {}

    scheduler = ActionScheduler(hass, entry)
    restore_mock = AsyncMock()

    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.Store",
        _FakeStore,
    )
    monkeypatch.setattr(scheduler, "_handle_sell_restore", restore_mock)
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.dt_util.utcnow",
        lambda: datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.dt_util.as_local",
        lambda value: value,
    )

    _FakeStore.saved_data = None
    _FakeStore.removed = False
    _FakeStore.load_data = {
        "work_mode": "Zero Export to Load",
        "prog_soc_entity": "number.prog3_soc",
        "prog_soc_value": 70.0,
        "restore_hour": 8,
        "sell_type": "morning",
        "timestamp": "2026-02-27T07:00:00+00:00",
    }

    await scheduler._check_pending_restore()

    assert restore_mock.await_count == 1
    assert restore_mock.await_args.args[0] == "morning"
