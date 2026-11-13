"""Lifecycle and lookup tests for the two-slot buy-window plan manager."""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.energy_optimizer import night_buy_window_manager as manager_module
from custom_components.energy_optimizer.const import (
    CONF_BUY_PRICE_SENSOR,
    CONF_HIGH_TARIFF_END_HOUR_SENSOR,
    CONF_HIGH_TARIFF_START_HOUR_SENSOR,
    DOMAIN,
)
from custom_components.energy_optimizer.helpers import (
    day_buy_window_missing_for_today,
)
from custom_components.energy_optimizer.night_buy_window import NightBuyWindowPlan
from custom_components.energy_optimizer.night_buy_window_manager import (
    BuyWindowPlanManager,
    NightBuyWindowPlanManager,
)

TZ = ZoneInfo("Europe/Warsaw")


def _entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {
        CONF_BUY_PRICE_SENSOR: "sensor.buy",
        CONF_HIGH_TARIFF_END_HOUR_SENSOR: "sensor.tariff_end",
        CONF_HIGH_TARIFF_START_HOUR_SENSOR: "sensor.tariff_start",
    }
    return entry


def _hass_with_tariff(end_hour: int | None, start_hour: int | None) -> MagicMock:
    """A hass whose high-tariff sensors report the given hours (None = missing)."""
    states = {
        "sensor.tariff_end": MagicMock(state=str(end_hour)) if end_hour is not None else None,
        "sensor.tariff_start": MagicMock(state=str(start_hour)) if start_hour is not None else None,
    }
    hass = MagicMock()
    hass.states.get.side_effect = lambda entity_id: states.get(entity_id)
    return hass


def _manager(*, tariff_end: int | None = 9, tariff_start: int | None = 17) -> NightBuyWindowPlanManager:
    manager = NightBuyWindowPlanManager(_hass_with_tariff(tariff_end, tariff_start), _entry())
    manager._async_save_snapshot = AsyncMock()
    return manager


def _night(end_day: date, *, price: float = 1.0) -> NightBuyWindowPlan:
    return NightBuyWindowPlan(
        start=datetime.combine(end_day - timedelta(days=1), datetime.min.time(), TZ).replace(hour=22),
        end=datetime.combine(end_day, datetime.min.time(), TZ).replace(hour=6),
        price=price,
    )


def _day(day: date, *, start_hour: int = 11, price: float = 0.5) -> NightBuyWindowPlan:
    return NightBuyWindowPlan(
        start=datetime.combine(day, datetime.min.time(), TZ).replace(hour=start_hour),
        end=datetime.combine(day, datetime.min.time(), TZ).replace(hour=start_hour + 2),
        price=price,
    )


def _hourly(day: date, hours: dict[int, float]) -> list[dict[str, object]]:
    return [
        {
            "time": datetime.combine(day, datetime.min.time(), TZ)
            .replace(hour=hour)
            .isoformat(),
            "price": price,
        }
        for hour, price in sorted(hours.items())
    ]


def _day_prices(day: date) -> list[dict[str, object]]:
    return _hourly(day, {9: 1.0, 10: 0.9, 11: 0.2, 12: 0.3, 13: 0.8, 14: 0.9, 15: 1.0, 16: 1.1})


def _night_prices(end_day: date) -> list[dict[str, object]]:
    start = _night(end_day).start
    end = _night(end_day).end
    prices: list[dict[str, object]] = []
    cursor = start.astimezone(UTC)
    index = 0
    while cursor < end.astimezone(UTC):
        prices.append({"time": cursor.astimezone(TZ).isoformat(), "price": 1.0 + index * 0.01})
        cursor += timedelta(hours=1)
        index += 1
    return prices


def _hass_with(manager: NightBuyWindowPlanManager) -> MagicMock:
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": {"buy_window_manager": manager}}}
    return hass


# --- rotation ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_night_plan_is_not_rotated_before_six_oh_one() -> None:
    manager = _manager()
    manager._upcoming = _night(date(2026, 10, 28))

    await manager.async_reconcile({}, now=datetime(2026, 10, 28, 6, 0, 30, tzinfo=TZ))

    assert manager._upcoming is not None
    assert manager._current is None


@pytest.mark.asyncio
async def test_night_plan_is_not_rotated_at_midnight_of_its_key_date() -> None:
    """Key date equal to today must not rotate while the night is still running."""
    manager = _manager()
    manager._upcoming = _night(date(2026, 10, 28))

    await manager.async_reconcile({}, now=datetime(2026, 10, 28, 0, 5, tzinfo=TZ))

    assert manager._upcoming is not None
    assert manager._current is None
    manager._async_save_snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_both_kinds_rotate_atomically_at_six_oh_one_with_one_save() -> None:
    manager = _manager()
    manager._upcoming = _night(date(2026, 10, 28))
    manager._day_upcoming = _day(date(2026, 10, 28))

    await manager.async_reconcile({}, now=datetime(2026, 10, 28, 6, 1, tzinfo=TZ))

    assert manager._current == _night(date(2026, 10, 28))
    assert manager._day_current == _day(date(2026, 10, 28))
    assert manager._upcoming is None and manager._day_upcoming is None
    manager._async_save_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_restart_after_rotation_time_self_heals_on_first_reconcile() -> None:
    manager = _manager()
    manager._upcoming = _night(date(2026, 10, 28))
    manager._day_upcoming = _day(date(2026, 10, 28))

    await manager.async_reconcile({}, now=datetime(2026, 10, 28, 7, 30, tzinfo=TZ))

    assert manager._current is not None
    assert manager._day_current is not None


@pytest.mark.asyncio
async def test_rotation_is_idempotent() -> None:
    manager = _manager()
    manager._upcoming = _night(date(2026, 10, 28))
    now = datetime(2026, 10, 28, 6, 1, tzinfo=TZ)

    await manager.async_reconcile({}, now=now)
    await manager.async_reconcile({}, now=now)

    manager._async_save_snapshot.assert_awaited_once()


# --- empty next at rotation -------------------------------------------------


@pytest.mark.asyncio
async def test_empty_next_at_rotation_recomputes_day_from_today_prices() -> None:
    manager = _manager()
    today = date(2026, 10, 28)

    await manager.async_reconcile(
        {"sensor.buy": {"prices_today": _day_prices(today)}},
        now=datetime(2026, 10, 28, 6, 1, tzinfo=TZ),
    )

    assert manager._day_current is not None
    assert manager._day_current.start == datetime(2026, 10, 28, 11, tzinfo=TZ)
    assert manager._current is None


@pytest.mark.asyncio
async def test_empty_next_without_data_leaves_window_empty_and_drops_stale_plan() -> None:
    manager = _manager()
    manager._current = _night(date(2026, 10, 27))
    manager._day_current = _day(date(2026, 10, 27))

    await manager.async_reconcile({}, now=datetime(2026, 10, 28, 6, 1, tzinfo=TZ))

    assert manager._current is None
    assert manager._day_current is None
    manager._async_save_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_night_recomputed_at_rotation_when_complete_data_exists() -> None:
    manager = _manager()
    end_day = date(2026, 10, 28)

    await manager.async_reconcile(
        {"sensor.buy": {"prices": _night_prices(end_day)}},
        now=datetime(2026, 10, 28, 6, 1, tzinfo=TZ),
    )

    assert manager._current is not None
    assert manager._current.plan_date == end_day


@pytest.mark.asyncio
async def test_failed_planning_does_not_overwrite_valid_next() -> None:
    manager = _manager()
    plan = _night(date(2026, 10, 28))
    day_plan = _day(date(2026, 10, 28))
    manager._upcoming = plan
    manager._day_upcoming = day_plan

    await manager.async_reconcile(
        {"sensor.buy": {"prices": [], "prices_tomorrow": []}},
        now=datetime(2026, 10, 27, 15, 0, tzinfo=TZ),
    )

    assert manager._upcoming == plan
    assert manager._day_upcoming == day_plan
    manager._async_save_snapshot.assert_not_awaited()


# --- planning ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_planning_creates_independent_night_and_day_plans_after_fourteen() -> None:
    manager = _manager()
    tomorrow = date(2026, 10, 28)
    payload = {
        "prices": _night_prices(tomorrow) + _day_prices(tomorrow),
        "prices_tomorrow": _day_prices(tomorrow),
    }

    await manager.async_reconcile(
        {"sensor.buy": payload}, now=datetime(2026, 10, 27, 14, 0, tzinfo=TZ)
    )

    assert manager._upcoming is not None and manager._upcoming.plan_date == tomorrow
    assert manager._day_upcoming is not None and manager._day_upcoming.plan_date == tomorrow
    manager._async_save_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_day_plan_is_created_even_when_night_data_is_incomplete() -> None:
    manager = _manager()
    tomorrow = date(2026, 10, 28)

    await manager.async_reconcile(
        {"sensor.buy": {"prices_tomorrow": _day_prices(tomorrow)}},
        now=datetime(2026, 10, 27, 14, 0, tzinfo=TZ),
    )

    assert manager._upcoming is None
    assert manager._day_upcoming is not None


@pytest.mark.asyncio
async def test_nothing_is_planned_before_fourteen() -> None:
    manager = _manager()
    tomorrow = date(2026, 10, 28)

    await manager.async_reconcile(
        {"sensor.buy": {"prices_tomorrow": _day_prices(tomorrow)}},
        now=datetime(2026, 10, 27, 13, 59, tzinfo=TZ),
    )

    assert manager._day_upcoming is None
    manager._async_save_snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_spring_forward_night_is_planned_and_rotated() -> None:
    """The 22:00-06:00 night of 2026-03-29 has seven elapsed hours."""
    manager = _manager()
    end_day = date(2026, 3, 29)
    prices = _night_prices(end_day)
    assert len(prices) == 7

    await manager.async_reconcile(
        {"sensor.buy": {"prices": prices}},
        now=datetime(2026, 3, 28, 14, 0, tzinfo=TZ),
    )
    assert manager._upcoming is not None
    assert manager._upcoming.end == datetime(2026, 3, 29, 6, tzinfo=TZ)

    await manager.async_reconcile({}, now=datetime(2026, 3, 29, 6, 1, tzinfo=TZ))
    assert manager._current is not None
    assert manager._upcoming is None


# --- persistence ------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_failure_leaves_memory_untouched_for_both_kinds() -> None:
    manager = NightBuyWindowPlanManager(MagicMock(), _entry())
    manager._async_save_snapshot = AsyncMock(side_effect=OSError("store unavailable"))
    manager._upcoming = _night(date(2026, 10, 28))
    manager._day_upcoming = _day(date(2026, 10, 28))
    manager._executed_start = "2026-10-27T22:00:00+01:00"

    await manager.async_reconcile({}, now=datetime(2026, 10, 28, 6, 1, tzinfo=TZ))

    assert manager._current is None and manager._day_current is None
    assert manager._upcoming is not None and manager._day_upcoming is not None
    assert manager._executed_start == "2026-10-27T22:00:00+01:00"


@pytest.mark.asyncio
async def test_restore_migrates_old_night_store_into_two_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _night(date(2026, 10, 28)).as_dict()
    old_store = MagicMock()
    old_store.async_load = AsyncMock(
        return_value={
            "current": None,
            "upcoming": plan,
            "executed_start_time": "2026-10-27T22:00:00+01:00",
        }
    )
    new_store = MagicMock()
    new_store.async_load = AsyncMock(return_value=None)
    new_store.async_save = AsyncMock()
    monkeypatch.setattr(manager_module, "night_buy_window_store", lambda *_: old_store)
    monkeypatch.setattr(manager_module, "Store", lambda *a, **k: new_store)
    manager = NightBuyWindowPlanManager(MagicMock(), _entry())

    await manager.async_restore()

    assert manager._upcoming == _night(date(2026, 10, 28))
    assert manager._current is None
    assert manager._day_current is None and manager._day_upcoming is None
    assert manager._executed_start == "2026-10-27T22:00:00+01:00"
    saved = new_store.async_save.await_args.args[0]
    assert saved["night"]["next"] == plan
    assert saved["day"] == {"window": None, "next": None}
    assert saved["executed_start_time"] == "2026-10-27T22:00:00+01:00"


@pytest.mark.asyncio
async def test_restore_reads_new_schema_without_touching_old_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    night = _night(date(2026, 10, 28)).as_dict()
    day = _day(date(2026, 10, 28)).as_dict()
    new_store = MagicMock()
    new_store.async_load = AsyncMock(
        return_value={
            "night": {"window": None, "next": night},
            "day": {"window": day, "next": None},
            "executed_start_time": None,
        }
    )
    new_store.async_save = AsyncMock()
    old_loader = MagicMock()
    monkeypatch.setattr(manager_module, "night_buy_window_store", old_loader)
    monkeypatch.setattr(manager_module, "Store", lambda *a, **k: new_store)
    manager = NightBuyWindowPlanManager(MagicMock(), _entry())

    await manager.async_restore()

    old_loader.assert_not_called()
    assert manager._upcoming == _night(date(2026, 10, 28))
    assert manager._day_current == _day(date(2026, 10, 28))
    new_store.async_save.assert_not_awaited()


# --- serialisation ----------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_and_claim_never_save_concurrently() -> None:
    manager = NightBuyWindowPlanManager(MagicMock(), _entry())
    tomorrow = date(2026, 10, 28)
    manager._upcoming = _night(tomorrow)
    active = 0
    max_active = 0

    async def slow_save(*_args, **_kwargs) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        for _ in range(5):
            await asyncio.sleep(0)
        active -= 1

    manager._async_save_snapshot = slow_save

    results = await asyncio.gather(
        manager.async_reconcile(
            {"sensor.buy": {"prices_tomorrow": _day_prices(tomorrow)}},
            now=datetime(2026, 10, 27, 14, 5, tzinfo=TZ),
        ),
        manager.async_claim(manager._upcoming.start),
    )

    assert results[1] is True
    assert max_active == 1


# --- lookup by key ----------------------------------------------------------


def test_new_manager_alias_is_exported() -> None:
    assert BuyWindowPlanManager is NightBuyWindowPlanManager


def test_get_plan_matches_by_key_in_either_slot() -> None:
    manager = _manager()
    manager._day_current = _day(date(2026, 10, 27))
    manager._day_upcoming = _day(date(2026, 10, 28), start_hour=12)

    assert manager.get_plan("day", date(2026, 10, 27)).start.hour == 11
    assert manager.get_plan("day", date(2026, 10, 28)).start.hour == 12
    assert manager.get_plan("day", date(2026, 10, 29)) is None
    assert manager.get_plan("night", date(2026, 10, 28)) is None


@pytest.mark.parametrize(
    ("now", "expected_key"),
    [
        (datetime(2026, 10, 27, 18, 0, tzinfo=TZ), date(2026, 10, 28)),
        (datetime(2026, 10, 27, 22, 30, tzinfo=TZ), date(2026, 10, 28)),
        (datetime(2026, 10, 28, 2, 0, tzinfo=TZ), date(2026, 10, 28)),
        (datetime(2026, 10, 28, 5, 59, tzinfo=TZ), date(2026, 10, 28)),
        (datetime(2026, 10, 28, 10, 0, tzinfo=TZ), None),
    ],
)
def test_active_night_plan_does_not_depend_on_calendar_day(
    now: datetime, expected_key: date | None
) -> None:
    manager = _manager()
    key = date(2026, 10, 28)
    if now >= datetime(2026, 10, 28, 6, 1, tzinfo=TZ):
        manager._current = _night(key)
    else:
        manager._upcoming = _night(key)

    plan = manager.get_active_plan("night", now)

    assert (plan.plan_date if plan is not None else None) == expected_key


def test_get_active_plan_prefers_earliest_ending_plan() -> None:
    manager = _manager()
    manager._current = _night(date(2026, 10, 28))
    manager._upcoming = _night(date(2026, 10, 29))

    plan = manager.get_active_plan("night", datetime(2026, 10, 28, 2, 0, tzinfo=TZ))

    assert plan.plan_date == date(2026, 10, 28)


def test_day_plan_requires_complete_finite_coverage_of_the_tariff_range() -> None:
    manager = _manager()
    day = date(2026, 10, 28)

    incomplete = _day_prices(day)[:-1]
    incomplete.append({"time": datetime(2026, 10, 28, 16, tzinfo=TZ).isoformat(), "price": float("inf")})

    assert manager._day_plan(incomplete, "sensor.buy", plan_date=day, local_tz=TZ) is None


def test_day_plan_breaks_ties_by_earlier_start() -> None:
    manager = _manager()
    day = date(2026, 10, 28)
    # 10:00-12:00 and 14:00-16:00 both average 1.0; the former closest-to-13:00
    # rule picked 14:00, the earlier-start rule picks 10:00.
    prices = _hourly(
        day,
        {9: 2.0, 10: 1.0, 11: 1.0, 12: 2.0, 13: 2.0, 14: 1.0, 15: 1.0, 16: 2.0},
    )

    plan = manager._day_plan(prices, "sensor.buy", plan_date=day, local_tz=TZ)

    assert plan is not None
    assert plan.start.hour == 10
    assert plan.end.hour == 12


def test_day_plan_range_follows_the_high_tariff_sensors() -> None:
    manager = _manager(tariff_end=13, tariff_start=17)
    day = date(2026, 10, 28)

    plan = manager._day_plan(_day_prices(day), "sensor.buy", plan_date=day, local_tz=TZ)

    assert plan is not None
    assert plan.start == datetime(2026, 10, 28, 13, tzinfo=TZ)
    assert plan.end == datetime(2026, 10, 28, 15, tzinfo=TZ)


def test_day_plan_falls_back_to_13_to_15_when_tariff_sensors_are_missing() -> None:
    manager = _manager(tariff_end=None, tariff_start=None)
    day = date(2026, 10, 28)

    plan = manager._day_plan(_day_prices(day), "sensor.buy", plan_date=day, local_tz=TZ)

    assert plan is not None
    assert plan.start == datetime(2026, 10, 28, 13, tzinfo=TZ)
    assert plan.end == datetime(2026, 10, 28, 15, tzinfo=TZ)


@pytest.mark.parametrize(("tariff_end", "tariff_start"), [(14, 15), (15, 13), (13, 13)])
def test_day_plan_is_none_when_tariff_range_is_shorter_than_two_hours(
    tariff_end: int, tariff_start: int
) -> None:
    manager = _manager(tariff_end=tariff_end, tariff_start=tariff_start)
    day = date(2026, 10, 28)

    assert manager._day_plan(_day_prices(day), "sensor.buy", plan_date=day, local_tz=TZ) is None


def test_day_buy_window_is_missing_only_with_a_manager_and_no_plan_for_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "custom_components.energy_optimizer.helpers.dt_util.utcnow",
        lambda: datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
    )
    manager = _manager()
    hass = _hass_with(manager)

    assert day_buy_window_missing_for_today(hass, entry_id="entry-1") is True

    manager._day_upcoming = _day(date(2026, 10, 28))
    assert day_buy_window_missing_for_today(hass, entry_id="entry-1") is False

    hass.data = {DOMAIN: {"entry-1": {}}}
    assert day_buy_window_missing_for_today(hass, entry_id="entry-1") is False
