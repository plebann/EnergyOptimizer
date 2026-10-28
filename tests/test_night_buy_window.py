"""Tests for persisted 22:00--06:00 night buy-window planning."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.energy_optimizer.night_buy_window import (
    NightBuyWindowPlan,
    build_night_buy_window_plan,
    night_window_bounds,
)
from custom_components.energy_optimizer.const import CONF_BUY_PRICE_SENSOR
from custom_components.energy_optimizer.coordinator import EnergyOptimizerCoordinator
from custom_components.energy_optimizer.entities.sensors.pricing import (
    NightBuyWindowSensor,
    NightBuyWindowTomorrowSensor,
)


TZ = ZoneInfo("Europe/Warsaw")
FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "night_buy_window"
    / "prices_2026-10-27_28.json"
)


def _night_prices(*, start: datetime, values: list[float]) -> list[dict[str, object]]:
    return [
        {"time": (start + timedelta(hours=index)).isoformat(), "price": value}
        for index, value in enumerate(values)
    ]


def _utc_night_prices(end_date: date, values: list[float]) -> list[dict[str, object]]:
    """Build hourly records from elapsed UTC instants for DST tests."""
    start, end = night_window_bounds(end_date, TZ)
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    instants = []
    current = start_utc
    while current < end_utc:
        instants.append(current)
        current += timedelta(hours=1)
    assert len(instants) == len(values)
    return [
        {"time": instant.isoformat(), "price": price}
        for instant, price in zip(instants, values, strict=True)
    ]


@pytest.mark.unit
def test_historical_replay_selects_twenty_two_to_midnight() -> None:
    """The issue #63 history selects 22:00--00:00 and does not expand."""
    prices = json.loads(FIXTURE.read_text(encoding="utf-8"))

    plan = build_night_buy_window_plan(
        prices,
        "sensor.pstryk_energy_pstryk_current_buy_price",
        end_date=date(2026, 10, 28),
        local_tz=TZ,
    )

    assert plan == NightBuyWindowPlan(
        start=datetime(2026, 10, 27, 22, tzinfo=TZ),
        end=datetime(2026, 10, 28, 0, tzinfo=TZ),
        price=pytest.approx(0.935),
    )


@pytest.mark.unit
def test_night_plan_expands_at_literal_one_hundred_ten_percent() -> None:
    """An adjacent hour at exactly 110% of the seed remains eligible."""
    start, _ = night_window_bounds(date(2026, 10, 28), TZ)
    prices = _night_prices(
        start=start,
        values=[1.50, 1.00, 1.00, 1.10, 1.60, 1.70, 1.80, 1.90],
    )

    plan = build_night_buy_window_plan(
        prices, "sensor.buy", end_date=date(2026, 10, 28), local_tz=TZ
    )

    assert plan is not None
    assert plan.start == datetime(2026, 10, 27, 23, tzinfo=TZ)
    assert plan.end == datetime(2026, 10, 28, 2, tzinfo=TZ)
    assert plan.price == pytest.approx((1.0 + 1.0 + 1.1) / 3)


@pytest.mark.unit
def test_night_plan_requires_every_hour_in_the_continuous_range() -> None:
    """A missing record must not establish a plan from partial prices."""
    start, _ = night_window_bounds(date(2026, 10, 28), TZ)
    prices = _night_prices(start=start, values=[1.0] * 8)
    del prices[3]

    assert (
        build_night_buy_window_plan(
            prices, "sensor.buy", end_date=date(2026, 10, 28), local_tz=TZ
        )
        is None
    )

    prices = _night_prices(start=start, values=[1.0] * 8)
    prices[2]["price"] = "invalid"
    assert (
        build_night_buy_window_plan(
            prices, "sensor.buy", end_date=date(2026, 10, 28), local_tz=TZ
        )
        is None
    )


@pytest.mark.unit
def test_night_plan_rejects_duplicate_or_invalid_hour() -> None:
    """Ambiguous or non-numeric prices fail closed."""
    start, _ = night_window_bounds(date(2026, 10, 28), TZ)
    prices = _night_prices(start=start, values=[1.0] * 8)
    prices.append({"time": start.isoformat(), "price": 1.0})
    assert (
        build_night_buy_window_plan(
            prices, "sensor.buy", end_date=date(2026, 10, 28), local_tz=TZ
        )
        is None
    )


@pytest.mark.unit
def test_fall_back_night_accepts_both_local_two_oclock_instants() -> None:
    """The repeated local hour is two distinct elapsed hourly records."""
    prices = _utc_night_prices(date(2026, 10, 25), [1.0] * 9)

    plan = build_night_buy_window_plan(
        prices, "sensor.buy", end_date=date(2026, 10, 25), local_tz=TZ
    )

    assert plan is not None
    assert plan.duration_hours == 9
    assert plan.start.astimezone(UTC) == datetime(2026, 10, 24, 20, tzinfo=UTC)
    assert plan.end.astimezone(UTC) == datetime(2026, 10, 25, 5, tzinfo=UTC)


@pytest.mark.unit
def test_spring_forward_night_does_not_require_nonexistent_two_oclock() -> None:
    """The skipped local hour is absent from the elapsed UTC sequence."""
    prices = _utc_night_prices(date(2026, 3, 29), [1.0] * 7)

    plan = build_night_buy_window_plan(
        prices, "sensor.buy", end_date=date(2026, 3, 29), local_tz=TZ
    )

    assert plan is not None
    assert plan.duration_hours == 7


@pytest.mark.unit
def test_fall_back_rejects_duplicate_elapsed_instant() -> None:
    """Different textual offsets for the same instant are still duplicates."""
    prices = _utc_night_prices(date(2026, 10, 25), [1.0] * 9)
    duplicate_instant = prices[4]["time"]
    prices.append({"time": duplicate_instant, "price": 2.0})

    assert (
        build_night_buy_window_plan(
            prices, "sensor.buy", end_date=date(2026, 10, 25), local_tz=TZ
        )
        is None
    )


@pytest.mark.asyncio
async def test_coordinator_creates_first_valid_plan_from_combined_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The coordinator snapshots `prices` and creates one immutable next plan."""
    now = datetime(2026, 10, 27, 14, 0, tzinfo=TZ)
    prices = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source_state = SimpleNamespace(state="1.0", attributes={"prices": prices})
    hass = MagicMock()
    hass.states.get.side_effect = lambda entity_id: (
        source_state if entity_id == "sensor.buy" else None
    )
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {CONF_BUY_PRICE_SENSOR: "sensor.buy"}
    coordinator = EnergyOptimizerCoordinator(hass, entry)
    coordinator._night_buy_window_manager._async_save_snapshot = AsyncMock()
    monkeypatch.setattr(
        "custom_components.energy_optimizer.coordinator.dt_util.now", lambda: now
    )

    data = await coordinator._async_update_data()

    assert data["price_payloads"]["sensor.buy"]["prices"] == prices
    assert data["price_payloads"]["sensor.buy"]["prices"] is not prices
    assert data["night_buy_window_plans"]["upcoming"] == {
        "start_time": "2026-10-27T22:00:00+01:00",
        "end_time": "2026-10-28T00:00:00+01:00",
        "duration_hours": 2,
        "price": pytest.approx(0.935),
        "validated_complete": True,
    }

    prices[0]["price"] = 99.0
    repeated_data = await coordinator._async_update_data()
    assert repeated_data["night_buy_window_plans"]["upcoming"]["price"] == pytest.approx(
        0.935
    )


@pytest.mark.unit
def test_night_sensors_publish_persisted_plan_with_rotation_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both sensors expose the active plan before 06:01, then split at rotation."""
    plan = {
        "start_time": "2026-10-27T22:00:00+01:00",
        "end_time": "2026-10-28T00:00:00+01:00",
        "duration_hours": 2,
        "price": 0.935,
        "validated_complete": True,
    }
    coordinator = MagicMock()
    coordinator.data = {"night_buy_window_plans": {"current": plan, "upcoming": plan}}
    entry = MagicMock(entry_id="entry-1", data={}, options={})
    config = {CONF_BUY_PRICE_SENSOR: "sensor.buy"}
    current = NightBuyWindowSensor(coordinator, entry, config)
    tomorrow = NightBuyWindowTomorrowSensor(coordinator, entry, config)

    monkeypatch.setattr(
        "custom_components.energy_optimizer.entities.sensors.pricing.dt_util.now",
        lambda: datetime(2026, 10, 28, 6, 0, tzinfo=TZ),
    )
    assert current.native_value == "22:00-00:00"
    assert tomorrow.native_value == "22:00-00:00"

    coordinator.data["night_buy_window_plans"]["upcoming"] = None
    monkeypatch.setattr(
        "custom_components.energy_optimizer.entities.sensors.pricing.dt_util.now",
        lambda: datetime(2026, 10, 28, 6, 1, tzinfo=TZ),
    )
    assert current.native_value == "22:00-00:00"
    assert tomorrow.native_value is None
