"""Quarter-hour sell-price window calculations for Energy Optimizer."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

MIDDAY_START = time(8, 0)
MIDDAY_END = time(16, 0)
WINDOW_SLOTS = 8
SLOT_DURATION = timedelta(minutes=15)
HOUR_DURATION = timedelta(hours=1)


@dataclass
class QuarterHourPricePoint:
    """Normalized sell-price sample for one quarter-hour slot."""

    start_local: datetime
    end_local: datetime
    business_date: date
    sell_price_value: float
    source_period: str
    source_entity_id: str


@dataclass
class MiddaySellWindowResult:
    """Result of the cheapest midday sell-price window selection."""

    start_local: datetime
    end_local: datetime
    total_cost: float
    average_price: float
    slot_count: int = field(default=WINDOW_SLOTS)


def _parse_entry_time(raw_time: Any, local_tz: tzinfo) -> datetime | None:
    """Parse one hourly source timestamp into local time."""
    if isinstance(raw_time, datetime):
        parsed = raw_time
    elif isinstance(raw_time, str):
        try:
            parsed = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=local_tz)

    return parsed.astimezone(local_tz)


def expand_hourly_sell_prices(
    prices_today: list[dict[str, Any]],
    entity_id: str,
    current_day: date,
    local_tz: tzinfo,
) -> list[QuarterHourPricePoint]:
    """Expand current-day hourly sell prices into quarter-hour points."""
    points: list[QuarterHourPricePoint] = []

    for entry in prices_today:
        if not isinstance(entry, dict):
            _LOGGER.debug("Skipping non-dict hourly sell-price entry: %s", entry)
            continue

        raw_time = entry.get("time")
        raw_price = entry.get("price")
        if raw_time is None or raw_price is None:
            continue

        slot_start = _parse_entry_time(raw_time, local_tz)
        if slot_start is None or slot_start.date() != current_day:
            continue

        try:
            sell_price = float(raw_price)
        except (TypeError, ValueError):
            _LOGGER.debug("Skipping invalid hourly sell-price entry: %s", entry)
            continue

        source_period = f"{slot_start:%H:%M}-{(slot_start + HOUR_DURATION):%H:%M}"
        for quarter in range(4):
            quarter_start = slot_start + quarter * SLOT_DURATION
            quarter_end = quarter_start + SLOT_DURATION
            points.append(
                QuarterHourPricePoint(
                    start_local=quarter_start,
                    end_local=quarter_end,
                    business_date=current_day,
                    sell_price_value=sell_price,
                    source_period=source_period,
                    source_entity_id=entity_id,
                )
            )

    return sorted(points, key=lambda point: point.start_local)


def _filter_midday_points(
    points: list[QuarterHourPricePoint],
) -> list[QuarterHourPricePoint]:
    """Keep only quarter-hour slots fully inside 08:00-16:00."""
    return [
        point
        for point in points
        if point.start_local.time() >= MIDDAY_START
        and point.end_local.time() <= MIDDAY_END
    ]


def select_midday_window(
    points: list[QuarterHourPricePoint],
) -> MiddaySellWindowResult | None:
    """Select the cheapest contiguous 8-quarter-hour midday window."""
    midday_points = _filter_midday_points(sorted(points, key=lambda point: point.start_local))
    if len(midday_points) < WINDOW_SLOTS:
        return None

    best: MiddaySellWindowResult | None = None
    for index in range(len(midday_points) - WINDOW_SLOTS + 1):
        window = midday_points[index : index + WINDOW_SLOTS]
        contiguous = all(
            window[offset].end_local == window[offset + 1].start_local
            for offset in range(WINDOW_SLOTS - 1)
        )
        if not contiguous:
            continue

        total_cost = sum(point.sell_price_value for point in window)
        if best is None or total_cost < best.total_cost:
            best = MiddaySellWindowResult(
                start_local=window[0].start_local,
                end_local=window[-1].end_local,
                total_cost=total_cost,
                average_price=total_cost / WINDOW_SLOTS,
            )

    return best


def build_midday_sell_window_result(
    prices_today: list[dict[str, Any]],
    entity_id: str,
    *,
    now_local: datetime | None = None,
) -> MiddaySellWindowResult | None:
    """Build the cheapest midday sell window from hourly shared-state payload."""
    reference_now = now_local or dt_util.now()
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

    points = expand_hourly_sell_prices(
        prices_today,
        entity_id,
        reference_now.date(),
        reference_now.tzinfo,
    )
    return select_midday_window(points)


def format_sell_window(result: MiddaySellWindowResult) -> str:
    """Format a midday sell window result as HH:MM-HH:MM."""
    start = result.start_local.strftime("%H:%M")
    end = result.end_local.strftime("%H:%M")
    return f"{start}-{end}"


def find_cheapest_midday_sell_window(
    prices_today: list[dict[str, Any]],
    entity_id: str,
    *,
    now_local: datetime | None = None,
) -> MiddaySellWindowResult | None:
    """Compatibility wrapper for midday sell window calculation."""
    return build_midday_sell_window_result(
        prices_today,
        entity_id,
        now_local=now_local,
    )
