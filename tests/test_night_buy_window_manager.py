"""Tests for the persisted night buy-window lifecycle manager."""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.energy_optimizer.const import CONF_BUY_PRICE_SENSOR
from custom_components.energy_optimizer.night_buy_window import (
    NightBuyWindowPlan,
)
from custom_components.energy_optimizer.night_buy_window_manager import (
    NightBuyWindowPlanManager,
)

TZ = ZoneInfo("Europe/Warsaw")


def _entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {CONF_BUY_PRICE_SENSOR: "sensor.buy"}
    return entry


def _plan(end_day: date = date(2026, 10, 28)) -> NightBuyWindowPlan:
    return NightBuyWindowPlan(
        start=datetime.combine(end_day, datetime.min.time(), TZ),
        end=datetime.combine(end_day, datetime.min.time(), TZ),
        price=1.0,
    )


def _prices() -> list[dict[str, object]]:
    return [
        {"time": f"2026-10-27T{hour:02d}:00:00+01:00", "price": price}
        for hour, price in ((22, 0.974), (23, 0.896))
    ] + [
        {"time": f"2026-10-28T{hour:02d}:00:00+01:00", "price": price}
        for hour, price in (
            (0, 1.108),
            (1, 1.141),
            (2, 1.147),
            (3, 1.151),
            (4, 1.150),
            (5, 1.197),
        )
    ]


@pytest.mark.asyncio
async def test_reconcile_does_not_create_plan_before_fourteen() -> None:
    manager = NightBuyWindowPlanManager(MagicMock(), _entry())
    manager._async_save_snapshot = AsyncMock()

    await manager.async_reconcile(
        {"sensor.buy": {"prices": _prices()}},
        now=datetime(2026, 10, 27, 13, 59, tzinfo=TZ),
    )

    assert manager.get_morning_charge_start() is None
    manager._async_save_snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_accepts_first_valid_plan_at_fourteen() -> None:
    manager = NightBuyWindowPlanManager(MagicMock(), _entry())
    manager._async_save_snapshot = AsyncMock()

    await manager.async_reconcile(
        {"sensor.buy": {"prices": _prices()}},
        now=datetime(2026, 10, 27, 14, 0, tzinfo=TZ),
    )

    assert manager.get_morning_charge_start() == datetime(
        2026, 10, 27, 22, tzinfo=TZ
    )
    manager._async_save_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_waits_for_valid_payload_after_invalid_first_update() -> None:
    manager = NightBuyWindowPlanManager(MagicMock(), _entry())
    manager._async_save_snapshot = AsyncMock()
    incomplete = _prices()[:-1]

    await manager.async_reconcile(
        {"sensor.buy": {"prices": incomplete}},
        now=datetime(2026, 10, 27, 14, 0, tzinfo=TZ),
    )
    assert manager.get_morning_charge_start() is None

    await manager.async_reconcile(
        {"sensor.buy": {"prices": _prices()}},
        now=datetime(2026, 10, 27, 14, 5, tzinfo=TZ),
    )
    assert manager.get_morning_charge_start() is not None


@pytest.mark.asyncio
async def test_reconcile_rotates_upcoming_to_current_at_six_oh_one() -> None:
    manager = NightBuyWindowPlanManager(MagicMock(), _entry())
    manager._upcoming = NightBuyWindowPlan(
        start=datetime(2026, 10, 27, 22, tzinfo=TZ),
        end=datetime(2026, 10, 28, 6, tzinfo=TZ),
        price=1.0,
    )
    manager._executed_start = "2026-10-27T22:00:00+01:00"
    manager._async_save_snapshot = AsyncMock()

    await manager.async_reconcile(
        {}, now=datetime(2026, 10, 28, 6, 1, tzinfo=TZ)
    )

    assert manager._current is not None
    assert manager._current.end == datetime(2026, 10, 28, 6, tzinfo=TZ)
    assert manager.get_morning_charge_start() is None
    assert manager._executed_start is None
    manager._async_save_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_save_failure_does_not_publish_candidate() -> None:
    manager = NightBuyWindowPlanManager(MagicMock(), _entry())
    manager._async_save_snapshot = AsyncMock(side_effect=OSError("store unavailable"))

    await manager.async_reconcile(
        {"sensor.buy": {"prices": _prices()}},
        now=datetime(2026, 10, 27, 14, 0, tzinfo=TZ),
    )

    assert manager.get_morning_charge_start() is None


@pytest.mark.asyncio
async def test_claim_is_at_most_once() -> None:
    manager = NightBuyWindowPlanManager(MagicMock(), _entry())
    manager._upcoming = NightBuyWindowPlan(
        start=datetime(2026, 10, 27, 22, tzinfo=TZ),
        end=datetime(2026, 10, 28, 6, tzinfo=TZ),
        price=1.0,
    )
    manager._async_save_snapshot = AsyncMock()

    start = manager._upcoming.start
    assert await manager.async_claim(start) is True
    assert await manager.async_claim(start) is False
    manager._async_save_snapshot.assert_awaited_once()
