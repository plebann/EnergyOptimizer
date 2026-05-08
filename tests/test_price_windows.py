"""Tests for quarter-hour sell-price window calculations."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from custom_components.energy_optimizer.calculations.price_windows import (
    WINDOW_SLOTS,
    MiddaySellWindowResult,
    QuarterHourPricePoint,
    build_midday_sell_window_result,
    expand_hourly_sell_prices,
    format_sell_window,
    select_midday_window,
)

TZ = timezone(timedelta(hours=2))
TODAY = date(2026, 5, 8)
TOMORROW = date(2026, 5, 9)
ENTITY_ID = "sensor.sell_price"


def _hourly_entry(
    hour: int,
    price: float | str,
    *,
    day: date = TODAY,
) -> dict[str, object]:
    """Create one hourly source entry using the feature contract shape."""
    dt = datetime(day.year, day.month, day.day, hour, 0, tzinfo=TZ)
    return {"time": dt.isoformat(), "price": price}


def _full_day_entries(low_start_hour: int = 10, low_hours: int = 2) -> list[dict[str, object]]:
    """Create a full 08:00-16:00 hourly day where a contiguous range is cheapest."""
    entries: list[dict[str, object]] = []
    for hour in range(8, 16):
        is_low = low_start_hour <= hour < low_start_hour + low_hours
        entries.append(_hourly_entry(hour, 0.5 if is_low else 1.0))
    return entries


def _point_at(hour: int, minute: int, price: float) -> QuarterHourPricePoint:
    """Create one normalized quarter-hour point."""
    start = datetime(2026, 5, 8, hour, minute, tzinfo=TZ)
    return QuarterHourPricePoint(
        start_local=start,
        end_local=start + timedelta(minutes=15),
        business_date=TODAY,
        sell_price_value=price,
        source_period=f"{start:%H:%M}-{(start + timedelta(minutes=15)):%H:%M}",
        source_entity_id=ENTITY_ID,
    )


@pytest.mark.unit
def test_expand_hourly_sell_prices_creates_four_quarters_per_hour() -> None:
    points = expand_hourly_sell_prices([_hourly_entry(10, 0.42)], ENTITY_ID, TODAY, TZ)

    assert len(points) == 4
    assert [point.start_local.minute for point in points] == [0, 15, 30, 45]
    assert all(point.sell_price_value == pytest.approx(0.42) for point in points)


@pytest.mark.unit
def test_expand_hourly_sell_prices_filters_out_other_days() -> None:
    points = expand_hourly_sell_prices(
        [_hourly_entry(10, 0.42), _hourly_entry(10, 0.11, day=TOMORROW)],
        ENTITY_ID,
        TODAY,
        TZ,
    )

    assert len(points) == 4
    assert all(point.business_date == TODAY for point in points)


@pytest.mark.unit
def test_expand_hourly_sell_prices_skips_invalid_entries() -> None:
    points = expand_hourly_sell_prices(
        [
            _hourly_entry(10, 0.42),
            {"time": datetime(2026, 5, 8, 11, 0, tzinfo=TZ).isoformat()},
            {"price": 0.5},
            _hourly_entry(12, "bad"),
        ],
        ENTITY_ID,
        TODAY,
        TZ,
    )

    assert len(points) == 4
    assert points[0].start_local.hour == 10


@pytest.mark.unit
def test_select_midday_window_picks_cheapest_contiguous_eight_quarters() -> None:
    points = expand_hourly_sell_prices(_full_day_entries(low_start_hour=10), ENTITY_ID, TODAY, TZ)

    result = select_midday_window(points)

    assert result is not None
    assert result.start_local == datetime(2026, 5, 8, 10, 0, tzinfo=TZ)
    assert result.end_local == datetime(2026, 5, 8, 12, 0, tzinfo=TZ)
    assert result.slot_count == WINDOW_SLOTS
    assert result.total_cost == pytest.approx(4.0)


@pytest.mark.unit
def test_select_midday_window_breaks_ties_by_earliest_start() -> None:
    points = expand_hourly_sell_prices(_full_day_entries(low_start_hour=8, low_hours=8), ENTITY_ID, TODAY, TZ)

    result = select_midday_window(points)

    assert result is not None
    assert result.start_local == datetime(2026, 5, 8, 8, 0, tzinfo=TZ)
    assert result.end_local == datetime(2026, 5, 8, 10, 0, tzinfo=TZ)


@pytest.mark.unit
def test_select_midday_window_returns_none_when_less_than_eight_contiguous_quarters() -> None:
    points = expand_hourly_sell_prices([_hourly_entry(8, 0.4)], ENTITY_ID, TODAY, TZ)

    assert select_midday_window(points) is None


@pytest.mark.unit
def test_select_midday_window_returns_none_for_gap_in_required_window() -> None:
    points = [
        _point_at(8, 0, 1.0),
        _point_at(8, 15, 1.0),
        _point_at(8, 30, 1.0),
        _point_at(8, 45, 1.0),
        _point_at(9, 0, 1.0),
        _point_at(9, 15, 1.0),
        _point_at(9, 30, 1.0),
        _point_at(10, 0, 1.0),
    ]

    assert select_midday_window(points) is None


@pytest.mark.unit
def test_build_midday_sell_window_result_ignores_tomorrow_even_when_cheaper() -> None:
    result = build_midday_sell_window_result(
        [_hourly_entry(8, 1.0), _hourly_entry(9, 1.0)]
        + _full_day_entries(low_start_hour=12)
        + [_hourly_entry(8, 0.1, day=TOMORROW), _hourly_entry(9, 0.1, day=TOMORROW)],
        ENTITY_ID,
        now_local=datetime(2026, 5, 8, 12, 0, tzinfo=TZ),
    )

    assert result is not None
    assert result.start_local.date() == TODAY


@pytest.mark.unit
def test_build_midday_sell_window_result_returns_none_when_data_missing() -> None:
    result = build_midday_sell_window_result(
        [_hourly_entry(8, 1.0), _hourly_entry(9, 1.0)],
        ENTITY_ID,
        now_local=datetime(2026, 5, 8, 12, 0, tzinfo=TZ),
    )

    assert result is None


@pytest.mark.unit
def test_build_midday_sell_window_result_skips_invalid_hour_and_selects_other_window() -> None:
    entries = _full_day_entries(low_start_hour=10)
    entries[2] = _hourly_entry(10, "bad")

    result = build_midday_sell_window_result(
        entries,
        ENTITY_ID,
        now_local=datetime(2026, 5, 8, 12, 0, tzinfo=TZ),
    )

    assert result is not None
    assert result.start_local != datetime(2026, 5, 8, 10, 0, tzinfo=TZ)


@pytest.mark.unit
def test_format_sell_window_uses_hhmm_hhmm_format() -> None:
    result = MiddaySellWindowResult(
        start_local=datetime(2026, 5, 8, 12, 0, tzinfo=TZ),
        end_local=datetime(2026, 5, 8, 14, 0, tzinfo=TZ),
        total_cost=4.0,
    )

    assert format_sell_window(result) == "12:00-14:00"
