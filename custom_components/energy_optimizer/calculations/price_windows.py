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
ZERO_PRICE_THRESHOLD = 0.05


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


@dataclass
class RankedSellWindowResult:
    """Result of selecting the best and second-best hourly sell windows."""

    best_start_local: datetime
    best_price: float
    second_best_start_local: datetime
    second_best_price: float
    second_window_gap_pct: float | None


@dataclass
class HourlyBuyPriceEntry:
    """Normalized one-hour buy-price entry used for buy-window selection."""

    start_local: datetime
    end_local: datetime
    business_date: date
    buy_price_value: float
    source_entity_id: str


@dataclass
class BuyWindowResult:
    """Result of selecting the best buy window for one day/range."""

    start_local: datetime
    end_local: datetime
    average_price: float


@dataclass
class AverageBuyPriceResult:
    """Result of averaging buy prices across a resolved hourly window."""

    start_local: datetime
    end_local: datetime
    average_price: float


@dataclass(frozen=True, slots=True)
class ArbitrageBuyHourResult:
    """First future buy hour that satisfies a sell-margin threshold."""

    start_local: datetime | None
    average_price: float | None
    arbitrage_margin: float | None
    reason: str


@dataclass
class HourlySellPriceCandidate:
    """Normalized one-hour candidate used by ranked sell-window selection."""

    start_local: datetime
    end_local: datetime
    business_date: date
    sell_price_value: float
    source_entity_id: str


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


def find_first_arbitrage_buy_hour(
    prices: list[dict[str, Any]],
    entity_id: str,
    *,
    start_local: datetime,
    end_local: datetime,
    sell_price: float,
    min_arbitrage_margin: float,
    max_buy_price: float | None = None,
) -> ArbitrageBuyHourResult:
    """Find the first complete buy-price hour meeting arbitrage constraints.

    Source integrations may publish either one hourly point or four
    quarter-hour points. Quarter-hour samples are averaged only when all four
    expected slots are present. Any missing or malformed hour in the searched
    interval invalidates the lookup so callers can fail closed for arbitrage.
    """
    if start_local.tzinfo is None or end_local.tzinfo is None:
        raise ValueError("Arbitrage price bounds must be timezone-aware")
    if end_local <= start_local:
        return ArbitrageBuyHourResult(None, None, None, "empty_search_window")

    local_tz = start_local.tzinfo
    prices_by_hour: dict[datetime, list[tuple[int, float]]] = {}
    for entry in prices:
        if not isinstance(entry, dict):
            continue
        raw_time = entry.get("time")
        raw_price = entry.get("price")
        if raw_time is None or raw_price is None:
            continue

        point_local = _parse_entry_time(raw_time, local_tz)
        if point_local is None or not start_local <= point_local < end_local:
            continue
        if point_local.minute not in (0, 15, 30, 45):
            continue
        try:
            price = float(raw_price)
        except (TypeError, ValueError):
            continue

        hour_start = point_local.replace(minute=0, second=0, microsecond=0)
        prices_by_hour.setdefault(hour_start, []).append((point_local.minute, price))

    hour_start = start_local.replace(minute=0, second=0, microsecond=0)
    if hour_start < start_local:
        hour_start += HOUR_DURATION
    threshold = sell_price - min_arbitrage_margin
    rejected_by_max_buy_price = False
    while hour_start < end_local:
        samples = prices_by_hour.get(hour_start)
        if not samples:
            return ArbitrageBuyHourResult(None, None, None, "missing_buy_price")

        minutes = [minute for minute, _price in samples]
        if len(samples) == 1 and minutes == [0]:
            average_price = samples[0][1]
        elif len(samples) == 4 and sorted(minutes) == [0, 15, 30, 45]:
            average_price = sum(price for _minute, price in samples) / 4
        else:
            _LOGGER.debug(
                "Invalid buy-price samples for %s at %s: %s",
                entity_id,
                hour_start,
                samples,
            )
            return ArbitrageBuyHourResult(None, None, None, "incomplete_buy_price")

        arbitrage_margin = sell_price - average_price
        if average_price < threshold:
            if max_buy_price is not None and average_price > max_buy_price:
                rejected_by_max_buy_price = True
                hour_start += HOUR_DURATION
                continue
            return ArbitrageBuyHourResult(
                hour_start,
                average_price,
                arbitrage_margin,
                "enabled",
            )
        hour_start += HOUR_DURATION

    if rejected_by_max_buy_price:
        return ArbitrageBuyHourResult(
            None,
            None,
            None,
            "buy_price_above_reference_limit",
        )
    return ArbitrageBuyHourResult(None, None, None, "margin_not_reached")


def _is_window_within_range(
    start_local: datetime,
    end_local: datetime,
    current_day: date,
    range_start_hour: int,
    range_end_hour: int,
) -> bool:
    """Return True when a time window stays fully inside one same-day hour range."""
    range_start = datetime.combine(
        current_day,
        time(range_start_hour, 0),
        tzinfo=start_local.tzinfo,
    )
    range_end = datetime.combine(
        current_day,
        time(range_end_hour, 0),
        tzinfo=start_local.tzinfo,
    )
    return start_local >= range_start and end_local <= range_end


def _extract_ranked_hourly_candidates(
    prices: list[dict[str, Any]],
    entity_id: str,
    current_day: date,
    local_tz: tzinfo,
    range_start_hour: int,
    range_end_hour: int,
) -> list[HourlySellPriceCandidate]:
    """Extract one-hour ranked candidates fully inside the requested range."""
    candidates_by_start: dict[datetime, HourlySellPriceCandidate] = {}

    for entry in prices:
        if not isinstance(entry, dict):
            _LOGGER.debug("Skipping non-dict ranked sell-price entry: %s", entry)
            continue

        raw_time = entry.get("time")
        raw_price = entry.get("price")
        if raw_time is None or raw_price is None:
            continue

        start_local = _parse_entry_time(raw_time, local_tz)
        if start_local is None or start_local.date() != current_day:
            continue

        if (
            start_local.minute != 0
            or start_local.second != 0
            or start_local.microsecond != 0
        ):
            continue

        end_local = start_local + HOUR_DURATION
        if not _is_window_within_range(
            start_local,
            end_local,
            current_day,
            range_start_hour,
            range_end_hour,
        ):
            continue

        try:
            sell_price = float(raw_price)
        except (TypeError, ValueError):
            _LOGGER.debug("Skipping invalid ranked sell-price entry: %s", entry)
            continue

        if start_local in candidates_by_start:
            _LOGGER.debug(
                "Duplicate ranked sell-price entry detected for %s at %s",
                entity_id,
                start_local,
            )
            return []

        candidate = HourlySellPriceCandidate(
            start_local=start_local,
            end_local=end_local,
            business_date=current_day,
            sell_price_value=sell_price,
            source_entity_id=entity_id,
        )
        candidates_by_start[start_local] = candidate

    return sorted(candidates_by_start.values(), key=lambda candidate: candidate.start_local)


def _extract_buy_hourly_entries(
    prices: list[dict[str, Any]],
    entity_id: str,
    current_day: date,
    local_tz: tzinfo,
) -> list[HourlyBuyPriceEntry]:
    """Extract normalized one-hour buy-price entries for one evaluated day."""
    entries_by_start: dict[datetime, HourlyBuyPriceEntry] = {}

    for entry in prices:
        if not isinstance(entry, dict):
            _LOGGER.debug("Skipping non-dict buy-price entry: %s", entry)
            continue

        raw_time = entry.get("time")
        raw_price = entry.get("price")
        if raw_time is None or raw_price is None:
            continue

        start_local = _parse_entry_time(raw_time, local_tz)
        if start_local is None or start_local.date() != current_day:
            continue

        if (
            start_local.minute != 0
            or start_local.second != 0
            or start_local.microsecond != 0
        ):
            continue

        try:
            buy_price = float(raw_price)
        except (TypeError, ValueError):
            _LOGGER.debug("Skipping invalid buy-price entry: %s", entry)
            continue

        if start_local in entries_by_start:
            _LOGGER.debug(
                "Duplicate buy-price entry detected for %s at %s",
                entity_id,
                start_local,
            )
            return []

        entries_by_start[start_local] = HourlyBuyPriceEntry(
            start_local=start_local,
            end_local=start_local + HOUR_DURATION,
            business_date=current_day,
            buy_price_value=buy_price,
            source_entity_id=entity_id,
        )

    return sorted(entries_by_start.values(), key=lambda entry: entry.start_local)


def _expand_buy_window(
    entries_by_start: dict[datetime, HourlyBuyPriceEntry],
    seed_start: datetime,
    seed_end: datetime,
    seed_average: float,
    *,
    range_start_hour: int,
    range_end_hour: int,
    current_day: date,
) -> BuyWindowResult:
    """Expand a seeded buy window with adjacent hours near its initial average."""
    window_start = seed_start
    window_end = seed_end
    total_price = seed_average * 2
    hour_count = 2
    stop_left = False
    stop_right = False

    while not (stop_left and stop_right):
        threshold = seed_average * 1.02
        add_left: HourlyBuyPriceEntry | None = None
        add_right: HourlyBuyPriceEntry | None = None

        if not stop_left:
            left_start = window_start - HOUR_DURATION
            left_entry = entries_by_start.get(left_start)
            if left_entry is None or not _is_window_within_range(
                left_entry.start_local,
                left_entry.end_local,
                current_day,
                range_start_hour,
                range_end_hour,
            ):
                stop_left = True
            elif left_entry.buy_price_value <= threshold:
                add_left = left_entry
            else:
                stop_left = True

        if not stop_right:
            right_entry = entries_by_start.get(window_end)
            if right_entry is None or not _is_window_within_range(
                right_entry.start_local,
                right_entry.end_local,
                current_day,
                range_start_hour,
                range_end_hour,
            ):
                stop_right = True
            elif right_entry.buy_price_value <= threshold:
                add_right = right_entry
            else:
                stop_right = True

        if add_left is None and add_right is None:
            continue

        if add_left is not None:
            window_start = add_left.start_local
            total_price += add_left.buy_price_value
            hour_count += 1

        if add_right is not None:
            window_end = add_right.end_local
            total_price += add_right.buy_price_value
            hour_count += 1

    return BuyWindowResult(
        start_local=window_start,
        end_local=window_end,
        average_price=total_price / hour_count,
    )


def build_best_buy_window_result(
    prices: list[dict[str, Any]],
    entity_id: str,
    *,
    range_key: str,
    range_start_hour: int,
    range_end_hour: int,
    now_local: datetime | None = None,
) -> BuyWindowResult | None:
    """Build the best buy window for one day/range."""
    reference_now = now_local or dt_util.now()
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

    entries = _extract_buy_hourly_entries(
        prices,
        entity_id,
        reference_now.date(),
        reference_now.tzinfo,
    )
    if len(entries) < 2:
        return None

    entries_by_start = {entry.start_local: entry for entry in entries}
    candidates: list[BuyWindowResult] = []
    for entry in entries:
        second_entry = entries_by_start.get(entry.start_local + HOUR_DURATION)
        if second_entry is None:
            continue

        end_local = second_entry.end_local
        if not _is_window_within_range(
            entry.start_local,
            end_local,
            reference_now.date(),
            range_start_hour,
            range_end_hour,
        ):
            continue

        candidates.append(
            BuyWindowResult(
                start_local=entry.start_local,
                end_local=end_local,
                average_price=(
                    entry.buy_price_value + second_entry.buy_price_value
                )
                / 2,
            )
        )

    if not candidates:
        return None

    if range_key == "night":
        range_anchor = datetime.combine(
            reference_now.date(),
            time(range_end_hour, 0),
            tzinfo=reference_now.tzinfo,
        )
        seed = min(
            candidates,
            key=lambda candidate: (
                candidate.average_price,
                abs((range_anchor - candidate.end_local).total_seconds()),
                -candidate.end_local.timestamp(),
            ),
        )
    elif range_key == "day":
        range_anchor = datetime.combine(
            reference_now.date(),
            time(13, 0),
            tzinfo=reference_now.tzinfo,
        )
        seed = min(
            candidates,
            key=lambda candidate: (
                candidate.average_price,
                abs((candidate.start_local - range_anchor).total_seconds()),
                candidate.start_local,
            ),
        )
    else:
        raise ValueError(f"Unsupported buy-window range key: {range_key}")

    return _expand_buy_window(
        entries_by_start,
        seed.start_local,
        seed.end_local,
        seed.average_price,
        range_start_hour=range_start_hour,
        range_end_hour=range_end_hour,
        current_day=reference_now.date(),
    )


def build_average_buy_price_result(
    prices: list[dict[str, Any]],
    entity_id: str,
    *,
    start_hour: int,
    end_hour: int,
    now_local: datetime | None = None,
) -> AverageBuyPriceResult | None:
    """Build an average buy-price result for whole hours in the requested range."""
    reference_now = now_local or dt_util.now()
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

    entries = _extract_buy_hourly_entries(
        prices,
        entity_id,
        reference_now.date(),
        reference_now.tzinfo,
    )
    if not entries:
        return None

    def _hour_in_range(hour: int) -> bool:
        if end_hour <= start_hour:
            return hour >= start_hour or hour < end_hour
        return start_hour <= hour < end_hour

    matching_entries = [entry for entry in entries if _hour_in_range(entry.start_local.hour)]
    if not matching_entries:
        return None

    total_price = sum(entry.buy_price_value for entry in matching_entries)
    return AverageBuyPriceResult(
        start_local=matching_entries[0].start_local,
        end_local=matching_entries[-1].end_local,
        average_price=total_price / len(matching_entries),
    )


def build_ranked_sell_window_result(
    prices: list[dict[str, Any]],
    entity_id: str,
    *,
    range_start_hour: int,
    range_end_hour: int,
    now_local: datetime | None = None,
) -> RankedSellWindowResult | None:
    """Build the best and second-best one-hour sell windows for one day/range."""
    reference_now = now_local or dt_util.now()
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

    candidates = _extract_ranked_hourly_candidates(
        prices,
        entity_id,
        reference_now.date(),
        reference_now.tzinfo,
        range_start_hour,
        range_end_hour,
    )
    if len(candidates) < 2:
        return None

    ranked = sorted(
        candidates,
        key=lambda candidate: (-candidate.sell_price_value, candidate.start_local),
    )
    best = ranked[0]
    second_best = ranked[1]

    second_window_gap_pct: float | None = None
    if best.sell_price_value != 0:
        second_window_gap_pct = (
            (best.sell_price_value - second_best.sell_price_value)
            / best.sell_price_value
        ) * 100

    return RankedSellWindowResult(
        best_start_local=best.start_local,
        best_price=best.sell_price_value,
        second_best_start_local=second_best.start_local,
        second_best_price=second_best.sell_price_value,
        second_window_gap_pct=second_window_gap_pct,
    )


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

        if sell_price < ZERO_PRICE_THRESHOLD:
            sell_price = 0.0

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
    """Select the midday sell window per zero-price expansion and 8-slot fallback rules."""
    midday_points = _filter_midday_points(sorted(points, key=lambda point: point.start_local))
    if not midday_points:
        return None

    # Zero mode: when >2 midday hours are zero-priced, span from the earliest
    # zero hour start to the latest zero hour end (including non-zero gaps).
    zero_hour_starts = sorted(
        {
            point.start_local.replace(minute=0, second=0, microsecond=0)
            for point in midday_points
            if point.sell_price_value == 0
        }
    )
    if len(zero_hour_starts) > 2:
        window_start = zero_hour_starts[0]
        window_end = zero_hour_starts[-1] + HOUR_DURATION
        window_points = [
            point
            for point in midday_points
            if point.start_local >= window_start and point.end_local <= window_end
        ]
        if not window_points:
            return None

        total_cost = sum(point.sell_price_value for point in window_points)
        slot_count = len(window_points)
        return MiddaySellWindowResult(
            start_local=window_start,
            end_local=window_end,
            total_cost=total_cost,
            average_price=total_cost / slot_count,
            slot_count=slot_count,
        )

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
