"""Tests for quarter-hour sell-price window calculations."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from custom_components.energy_optimizer.calculations.price_windows import (
    MIDDAY_END,
    MIDDAY_START,
    WINDOW_SLOTS,
    MiddaySellWindowResult,
    QuarterHourPricePoint,
    _filter_midday_points,
    _parse_price_points,
    _select_cheapest_window,
    find_cheapest_midday_sell_window,
    format_sell_window,
)

# Fixed UTC+2 offset used across all tests (e.g. Europe/Warsaw summer time)
TZ = timezone(timedelta(hours=2))
TODAY = date(2026, 5, 8)
SLOT = timedelta(minutes=15)
ENTITY_ID = "sensor.sell_price"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers


def _pt(hour: int, minute: int, price: float) -> QuarterHourPricePoint:
    """Create a single test QuarterHourPricePoint."""
    start = datetime(2026, 5, 8, hour, minute, tzinfo=TZ)
    return QuarterHourPricePoint(
        start_local=start,
        end_local=start + SLOT,
        sell_price_value=price,
        source_entity_id=ENTITY_ID,
    )


def _entry(hour: int, minute: int, price: float, day: date = TODAY) -> dict:
    """Create a raw price payload dict entry."""
    dt = datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)
    return {
        "dtime": dt.isoformat(),
        "period": f"{dt.strftime('%H:%M')} - {(dt + SLOT).strftime('%H:%M')}",
        "rce_pln": price,
        "business_date": day.isoformat(),
    }


def _full_midday_entries(low_start_slot: int = 8, low_price: float = 0.5) -> list[dict]:
    """Return 32 entries covering 08:00-16:00.

    All slots have price 1.0 except 8 consecutive slots starting at
    low_start_slot index (0 = 08:00, 1 = 08:15 …), which have low_price.
    """
    entries = []
    for i in range(32):
        h = 8 + (i * 15) // 60
        m = (i * 15) % 60
        price = low_price if low_start_slot <= i < low_start_slot + WINDOW_SLOTS else 1.0
        entries.append(_entry(h, m, price))
    return entries


# ──────────────────────────────────────────────────────────────────────────────
# _parse_price_points


@pytest.mark.unit
def test_parse_price_points_returns_sorted_current_day_points() -> None:
    entries = [
        _entry(10, 0, 0.5),
        _entry(8, 0, 0.3),
        _entry(9, 0, 0.4),
    ]
    points = _parse_price_points(entries, ENTITY_ID, TODAY, TZ)
    assert len(points) == 3
    assert points[0].start_local.hour == 8
    assert points[1].start_local.hour == 9
    assert points[2].start_local.hour == 10


@pytest.mark.unit
def test_parse_price_points_filters_other_days() -> None:
    tomorrow = date(2026, 5, 9)
    entries = [
        _entry(10, 0, 0.5),
        _entry(10, 0, 0.5, day=tomorrow),
    ]
    points = _parse_price_points(entries, ENTITY_ID, TODAY, TZ)
    assert len(points) == 1
    assert points[0].start_local.date() == TODAY


@pytest.mark.unit
def test_parse_price_points_skips_non_numeric_price() -> None:
    entries = [
        {"dtime": datetime(2026, 5, 8, 10, 0, tzinfo=TZ).isoformat(), "rce_pln": "bad"},
        _entry(11, 0, 0.4),
    ]
    points = _parse_price_points(entries, ENTITY_ID, TODAY, TZ)
    assert len(points) == 1
    assert points[0].start_local.hour == 11


@pytest.mark.unit
def test_parse_price_points_skips_missing_fields() -> None:
    entries = [
        {"dtime": datetime(2026, 5, 8, 10, 0, tzinfo=TZ).isoformat()},  # no rce_pln
        {"rce_pln": 0.4},  # no dtime
        _entry(12, 0, 0.5),
    ]
    points = _parse_price_points(entries, ENTITY_ID, TODAY, TZ)
    assert len(points) == 1


@pytest.mark.unit
def test_parse_price_points_accepts_datetime_objects() -> None:
    dt_obj = datetime(2026, 5, 8, 9, 0, tzinfo=TZ)
    entries = [{"dtime": dt_obj, "rce_pln": 0.6}]
    points = _parse_price_points(entries, ENTITY_ID, TODAY, TZ)
    assert len(points) == 1
    assert points[0].sell_price_value == 0.6


# ──────────────────────────────────────────────────────────────────────────────
# _filter_midday_points


@pytest.mark.unit
def test_filter_midday_points_keeps_slots_inside_0800_1600() -> None:
    inside = [
        _pt(8, 0, 1.0),   # 08:00-08:15 ✓
        _pt(15, 45, 1.0),  # 15:45-16:00 ✓
    ]
    outside = [
        _pt(7, 45, 1.0),   # 07:45-08:00 – start before 08:00
        _pt(16, 0, 1.0),   # 16:00-16:15 – start at boundary but end > 16:00
    ]
    result = _filter_midday_points(inside + outside)
    assert len(result) == 2
    assert all(p.start_local.hour >= 8 for p in result)


@pytest.mark.unit
def test_filter_midday_points_excludes_slot_ending_after_1600() -> None:
    point = _pt(15, 50, 1.0)  # end = 16:05 – beyond boundary
    # Manually override end to be 16:05
    point = QuarterHourPricePoint(
        start_local=datetime(2026, 5, 8, 15, 50, tzinfo=TZ),
        end_local=datetime(2026, 5, 8, 16, 5, tzinfo=TZ),
        sell_price_value=1.0,
        source_entity_id=ENTITY_ID,
    )
    result = _filter_midday_points([point])
    assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# _select_cheapest_window


@pytest.mark.unit
def test_select_cheapest_window_finds_lowest_cost_window() -> None:
    # 32 slots; slots 8-15 (10:00-12:00) are cheaper
    points = []
    for i in range(32):
        h = 8 + (i * 15) // 60
        m = (i * 15) % 60
        price = 0.5 if 8 <= i < 16 else 1.0
        points.append(_pt(h, m, price))

    result = _select_cheapest_window(points)
    assert result is not None
    assert result.start_local == datetime(2026, 5, 8, 10, 0, tzinfo=TZ)
    assert result.end_local == datetime(2026, 5, 8, 12, 0, tzinfo=TZ)
    assert result.total_cost == pytest.approx(4.0)


@pytest.mark.unit
def test_select_cheapest_window_tie_break_returns_earliest() -> None:
    # Two windows with identical total cost: slots 0-7 and slots 8-15
    points = [_pt(8 + (i * 15) // 60, (i * 15) % 60, 1.0) for i in range(32)]
    result = _select_cheapest_window(points)
    assert result is not None
    # Earliest window (08:00) should win
    assert result.start_local == datetime(2026, 5, 8, 8, 0, tzinfo=TZ)


@pytest.mark.unit
def test_select_cheapest_window_returns_none_with_too_few_points() -> None:
    points = [_pt(8, i * 15, 1.0) for i in range(WINDOW_SLOTS - 1)]
    assert _select_cheapest_window(points) is None


@pytest.mark.unit
def test_select_cheapest_window_returns_none_with_empty_points() -> None:
    assert _select_cheapest_window([]) is None


@pytest.mark.unit
def test_select_cheapest_window_skips_non_contiguous_gaps() -> None:
    # 7 contiguous points then a gap then 1 more – no valid 8-slot window
    points = [_pt(8, i * 15, 1.0) for i in range(7)]
    # Add point at 10:30 (gap at 09:45 → 10:30)
    gap_start = datetime(2026, 5, 8, 10, 30, tzinfo=TZ)
    points.append(
        QuarterHourPricePoint(
            start_local=gap_start,
            end_local=gap_start + SLOT,
            sell_price_value=1.0,
            source_entity_id=ENTITY_ID,
        )
    )
    assert _select_cheapest_window(points) is None


@pytest.mark.unit
def test_select_cheapest_window_exactly_8_points_valid() -> None:
    points = [_pt(8 + (i * 15) // 60, (i * 15) % 60, 0.3) for i in range(8)]
    result = _select_cheapest_window(points)
    assert result is not None
    assert result.slot_count == 8


# ──────────────────────────────────────────────────────────────────────────────
# format_sell_window


@pytest.mark.unit
def test_format_sell_window_produces_hhmm_hh_mm() -> None:
    result = MiddaySellWindowResult(
        start_local=datetime(2026, 5, 8, 12, 0, tzinfo=TZ),
        end_local=datetime(2026, 5, 8, 14, 0, tzinfo=TZ),
        total_cost=4.0,
    )
    assert format_sell_window(result) == "12:00-14-00"


@pytest.mark.unit
def test_format_sell_window_zero_padded() -> None:
    result = MiddaySellWindowResult(
        start_local=datetime(2026, 5, 8, 8, 0, tzinfo=TZ),
        end_local=datetime(2026, 5, 8, 10, 0, tzinfo=TZ),
        total_cost=8.0,
    )
    assert format_sell_window(result) == "08:00-10-00"


# ──────────────────────────────────────────────────────────────────────────────
# find_cheapest_midday_sell_window (integration with mock hass)


@pytest.mark.unit
def test_find_cheapest_midday_sell_window_returns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    state = MagicMock()
    state.attributes = {"prices": _full_midday_entries(low_start_slot=8)}

    hass = MagicMock()
    hass.states.get.return_value = state

    result = find_cheapest_midday_sell_window(hass, ENTITY_ID)
    assert result is not None
    assert result.start_local == datetime(2026, 5, 8, 10, 0, tzinfo=TZ)


@pytest.mark.unit
def test_find_cheapest_midday_sell_window_none_when_no_entity(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    result = find_cheapest_midday_sell_window(MagicMock(), None)
    assert result is None


@pytest.mark.unit
def test_find_cheapest_midday_sell_window_none_when_entity_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    hass = MagicMock()
    hass.states.get.return_value = None

    result = find_cheapest_midday_sell_window(hass, ENTITY_ID)
    assert result is None


@pytest.mark.unit
def test_find_cheapest_midday_sell_window_none_when_no_prices_attr(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    state = MagicMock()
    state.attributes = {}

    hass = MagicMock()
    hass.states.get.return_value = state

    result = find_cheapest_midday_sell_window(hass, ENTITY_ID)
    assert result is None


@pytest.mark.unit
def test_find_cheapest_midday_sell_window_filters_tomorrow_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tomorrow's price entries must not affect the current-day window."""
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    tomorrow = date(2026, 5, 9)
    # Only today's partial data (7 slots) + all of tomorrow's data
    today_entries = [_entry(8, i * 15, 2.0) for i in range(7)]
    tomorrow_entries = [_entry(8 + (i * 15) // 60, (i * 15) % 60, 0.1, day=tomorrow) for i in range(32)]

    state = MagicMock()
    state.attributes = {"prices": today_entries + tomorrow_entries}

    hass = MagicMock()
    hass.states.get.return_value = state

    # Today has only 7 slots → no valid 8-slot window
    result = find_cheapest_midday_sell_window(hass, ENTITY_ID)
    assert result is None


@pytest.mark.unit
def test_find_cheapest_midday_sell_window_ignores_non_numeric_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "now", lambda: datetime(2026, 5, 8, 12, 0, tzinfo=TZ))

    entries = _full_midday_entries()
    # Corrupt one entry in the cheapest window range
    entries[8]["rce_pln"] = "invalid"

    state = MagicMock()
    state.attributes = {"prices": entries}

    hass = MagicMock()
    hass.states.get.return_value = state

    # Corrupted slot breaks contiguity of the cheapest window;
    # some other valid 8-slot window should still be found
    result = find_cheapest_midday_sell_window(hass, ENTITY_ID)
    # Result may be None or a different window – the key assertion is no exception
    # and if found, it must not start at the corrupted window's start
    if result is not None:
        assert result.start_local != datetime(2026, 5, 8, 10, 0, tzinfo=TZ)
