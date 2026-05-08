"""Quarter-hour sell-price window calculations for Energy Optimizer."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Midday window boundaries
MIDDAY_START = time(8, 0)
MIDDAY_END = time(16, 0)
# Number of contiguous quarter-hour slots required for a valid window
WINDOW_SLOTS = 8
SLOT_DURATION = timedelta(minutes=15)


@dataclass
class QuarterHourPricePoint:
    """Normalized sell-price sample for one quarter-hour slot."""

    start_local: datetime
    end_local: datetime
    sell_price_value: float
    source_entity_id: str


@dataclass
class MiddaySellWindowResult:
    """Result of the cheapest midday sell-price window selection."""

    start_local: datetime
    end_local: datetime
    total_cost: float
    slot_count: int = field(default=WINDOW_SLOTS)


def _parse_price_points(
    prices: list[dict[str, Any]],
    entity_id: str,
    current_day: date,
    local_tz: Any,
) -> list[QuarterHourPricePoint]:
    """Parse and filter quarter-hour price points for the current local day.

    Returns points sorted by start time. Non-numeric or out-of-day entries are
    silently skipped with a debug log.
    """
    points: list[QuarterHourPricePoint] = []

    for entry in prices:
        try:
            dtime = entry.get("dtime")
            rce_pln = entry.get("rce_pln")
            if dtime is None or rce_pln is None:
                continue

            sell_price = float(rce_pln)

            if isinstance(dtime, datetime):
                slot_local = dtime.astimezone(local_tz)
            elif isinstance(dtime, str):
                dt_parsed = datetime.fromisoformat(dtime.replace("Z", "+00:00"))
                slot_local = dt_parsed.astimezone(local_tz)
            else:
                _LOGGER.debug("Unrecognized dtime type in price entry: %s", entry)
                continue

            if slot_local.date() != current_day:
                continue

            slot_end = slot_local + SLOT_DURATION
            points.append(
                QuarterHourPricePoint(
                    start_local=slot_local,
                    end_local=slot_end,
                    sell_price_value=sell_price,
                    source_entity_id=entity_id,
                )
            )
        except (ValueError, TypeError, AttributeError) as exc:
            _LOGGER.debug("Skipping invalid price entry %s: %s", entry, exc)

    return sorted(points, key=lambda p: p.start_local)


def _filter_midday_points(
    points: list[QuarterHourPricePoint],
) -> list[QuarterHourPricePoint]:
    """Filter points to those fully inside 08:00-16:00 local time."""
    return [
        p
        for p in points
        if p.start_local.time() >= MIDDAY_START and p.end_local.time() <= MIDDAY_END
    ]


def _select_cheapest_window(
    points: list[QuarterHourPricePoint],
) -> MiddaySellWindowResult | None:
    """Select the cheapest contiguous 8-quarter-hour window.

    When multiple windows share the same minimum total cost, the earliest is
    returned (since points are sorted by start time and the first match is kept).

    Returns None if no valid 8-slot contiguous window can be formed.
    """
    if len(points) < WINDOW_SLOTS:
        return None

    best: MiddaySellWindowResult | None = None
    for i in range(len(points) - WINDOW_SLOTS + 1):
        window = points[i : i + WINDOW_SLOTS]

        # Verify contiguity: each slot ends exactly where the next begins
        contiguous = all(
            window[j].end_local == window[j + 1].start_local
            for j in range(WINDOW_SLOTS - 1)
        )
        if not contiguous:
            continue

        total_cost = sum(p.sell_price_value for p in window)
        if best is None or total_cost < best.total_cost:
            best = MiddaySellWindowResult(
                start_local=window[0].start_local,
                end_local=window[-1].end_local,
                total_cost=total_cost,
            )

    return best


def format_sell_window(result: MiddaySellWindowResult) -> str:
    """Format a midday sell window result as HH:MM-HH-MM.

    Example: start=12:00, end=14:00 → "12:00-14-00"
    """
    start = result.start_local.strftime("%H:%M")
    end = result.end_local.strftime("%H-%M")
    return f"{start}-{end}"


def find_cheapest_midday_sell_window(
    hass: HomeAssistant,
    sell_price_entity_id: str | None,
) -> MiddaySellWindowResult | None:
    """Find the cheapest 8-quarter-hour sell-price window between 08:00 and 16:00.

    Reads the current-day price-series payload directly from the Home Assistant
    state object of the configured sell-price entity. Returns None when data is
    insufficient or invalid so the calling sensor can become unavailable.
    """
    if not sell_price_entity_id:
        _LOGGER.debug("No sell price entity configured for midday window calculation")
        return None

    state = hass.states.get(sell_price_entity_id)
    if state is None:
        _LOGGER.debug(
            "Sell price entity %s not found in HA state", sell_price_entity_id
        )
        return None

    prices = state.attributes.get("prices")
    if not isinstance(prices, list) or not prices:
        _LOGGER.debug(
            "Sell price entity %s has no 'prices' attribute list",
            sell_price_entity_id,
        )
        return None

    now_local = dt_util.now()
    current_day = now_local.date()
    local_tz = now_local.tzinfo

    points = _parse_price_points(prices, sell_price_entity_id, current_day, local_tz)
    midday_points = _filter_midday_points(points)
    result = _select_cheapest_window(midday_points)

    if result is None:
        _LOGGER.debug(
            "Could not find a full 8-quarter-hour midday window from %s",
            sell_price_entity_id,
        )
    return result
