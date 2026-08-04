"""Tests for the Program 4 solar-surplus reset."""
from __future__ import annotations

from datetime import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.energy_optimizer.const import (
    CONF_MIN_SOC_PV,
    CONF_PROG4_SOC_ENTITY,
)
from custom_components.energy_optimizer.decision_engine.program4_solar_reset import (
    async_run_program4_solar_reset,
)
from custom_components.energy_optimizer.scheduler.action_scheduler import ActionScheduler

pytestmark = pytest.mark.enable_socket


def _entry() -> MagicMock:
    """Build a minimal config entry for the reset routine."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {
        CONF_PROG4_SOC_ENTITY: "number.program4_soc",
        CONF_MIN_SOC_PV: 15,
    }
    return entry


def _patch_common_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    entry: MagicMock,
    start_hour: int = 9,
    afternoon_hour: int = 13,
    pv_kwh: float = 8.0,
    usage_kwh_per_hour: float = 1.0,
    battery_soc: float | None = 60.0,
) -> AsyncMock:
    """Patch external state and forecast inputs for a reset decision."""
    set_soc = AsyncMock()
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.program4_solar_reset.resolve_entry",
        lambda *_args, **_kwargs: entry,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.program4_solar_reset.resolve_prog4_start_time",
        lambda *_args, **_kwargs: time(start_hour),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.program4_solar_reset.resolve_tariff_start_hour",
        lambda *_args, **_kwargs: 15,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.program4_solar_reset.resolve_day_buy_window_start_hour",
        lambda *_args, **_kwargs: afternoon_hour,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.program4_solar_reset.get_required_prog4_soc_state",
        lambda *_args, **_kwargs: ("number.program4_soc", 60.0),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.program4_solar_reset.get_required_float_state",
        lambda *_args, **_kwargs: battery_soc,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.program4_solar_reset._has_configured_pv_forecast",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.program4_solar_reset.build_hourly_usage_array",
        lambda *_args, **_kwargs: [usage_kwh_per_hour] * 24,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.program4_solar_reset.get_pv_forecast_window",
        lambda *_args, **_kwargs: (pv_kwh, {}),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.program4_solar_reset.calculate_losses",
        lambda *_args, **_kwargs: (0.0, 0.0),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.decision_engine.program4_solar_reset.set_program_soc",
        set_soc,
    )
    return set_soc


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("battery_soc", "expected_target"),
    [(60.0, 15.0), (10.0, 10.0)],
)
async def test_resets_program4_to_min_of_battery_soc_and_min_soc_pv(
    monkeypatch: pytest.MonkeyPatch,
    battery_soc: float,
    expected_target: float,
) -> None:
    """A positive surplus resets Program 4 without exceeding battery SOC."""
    entry = _entry()
    set_soc = _patch_common_dependencies(
        monkeypatch,
        entry=entry,
        battery_soc=battery_soc,
    )

    await async_run_program4_solar_reset(MagicMock(), entry_id="entry-1")

    assert set_soc.await_count == 1
    assert set_soc.await_args.args[1:] == ("number.program4_soc", expected_target)


@pytest.mark.asyncio
async def test_does_not_reset_when_start_and_afternoon_charge_share_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reset compares hours only, so 10:00 is not before 10:01."""
    entry = _entry()
    set_soc = _patch_common_dependencies(
        monkeypatch,
        entry=entry,
        start_hour=10,
        afternoon_hour=10,
    )

    await async_run_program4_solar_reset(MagicMock(), entry_id="entry-1")

    set_soc.assert_not_awaited()


@pytest.mark.asyncio
async def test_does_not_reset_without_positive_forecast_surplus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero or negative forecast surplus leaves Program 4 unchanged."""
    entry = _entry()
    set_soc = _patch_common_dependencies(
        monkeypatch,
        entry=entry,
        pv_kwh=4.0,
        usage_kwh_per_hour=1.0,
    )

    await async_run_program4_solar_reset(MagicMock(), entry_id="entry-1")

    set_soc.assert_not_awaited()


@pytest.mark.asyncio
async def test_does_not_reset_when_required_input_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unavailable battery or load input prevents the safety-sensitive reset."""
    entry = _entry()
    set_soc = _patch_common_dependencies(
        monkeypatch,
        entry=entry,
        battery_soc=None,
    )

    await async_run_program4_solar_reset(MagicMock(), entry_id="entry-1")

    set_soc.assert_not_awaited()


def test_scheduler_uses_program4_start_hour_and_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduler follows Program 4's configured start time precisely."""
    entry = _entry()
    hass = MagicMock()
    hass.data = {"energy_optimizer": {"entry-1": {}}}
    captured: dict[str, int] = {}

    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_prog4_start_time",
        lambda *_args, **_kwargs: time(9, 30),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_tariff_start_hour",
        lambda *_args, **_kwargs: 15,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_day_buy_window_start_hour",
        lambda *_args, **_kwargs: 13,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_time_change",
        lambda _hass, _callback, *, hour, minute, second: captured.update(
            hour=hour,
            minute=minute,
            second=second,
        )
        or (lambda: None),
    )

    scheduler = ActionScheduler(hass, entry)
    scheduler._publish_schedule_snapshot = MagicMock()
    scheduler._schedule_program4_solar_reset()

    assert captured == {"hour": 9, "minute": 30, "second": 1}


def test_scheduler_does_not_schedule_reset_when_hours_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching hours do not meet the strict Program 4 reset gate."""
    entry = _entry()
    hass = MagicMock()
    hass.data = {"energy_optimizer": {"entry-1": {}}}
    track_time_change = MagicMock()

    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_prog4_start_time",
        lambda *_args, **_kwargs: time(10),
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_tariff_start_hour",
        lambda *_args, **_kwargs: 15,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.resolve_day_buy_window_start_hour",
        lambda *_args, **_kwargs: 10,
    )
    monkeypatch.setattr(
        "custom_components.energy_optimizer.scheduler.action_scheduler.async_track_time_change",
        track_time_change,
    )

    scheduler = ActionScheduler(hass, entry)
    scheduler._publish_schedule_snapshot = MagicMock()
    scheduler._schedule_program4_solar_reset()

    track_time_change.assert_not_called()


@pytest.mark.asyncio
async def test_scheduler_reschedules_program4_reset_when_start_time_changes() -> None:
    """A Program 4 start-time state change updates the reset listener."""
    scheduler = ActionScheduler(MagicMock(), _entry())
    scheduler._schedule_program4_solar_reset = MagicMock()

    await scheduler._handle_program4_start_time_change(MagicMock())

    scheduler._schedule_program4_solar_reset.assert_called_once()
