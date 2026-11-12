"""Market Window Resolver vocabulary: resolved windows, snapshot and adapters."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from enum import StrEnum
import logging
from math import isfinite
import re
from typing import TYPE_CHECKING, Final, Literal, Protocol, TypeVar

from homeassistant.util import dt as dt_util

from .calculations.price_windows import (
    build_average_buy_price_result,
    build_consume_window_result,
    build_ranked_sell_window_result,
)
from .const import (
    CONF_BUY_PRICE_SENSOR,
    CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR,
    CONF_DAYTIME_MIN_PRICE_SENSOR,
    CONF_EVENING_MAX_PRICE_HOUR_SENSOR,
    CONF_EVENING_MAX_PRICE_SENSOR,
    CONF_EVENING_SECOND_MAX_PRICE_HOUR_SENSOR,
    CONF_EVENING_SECOND_MAX_PRICE_SENSOR,
    CONF_HIGH_TARIFF_END_HOUR_SENSOR,
    CONF_HIGH_TARIFF_START_HOUR_SENSOR,
    CONF_MORNING_MAX_PRICE_HOUR_SENSOR,
    CONF_MORNING_MAX_PRICE_SENSOR,
    CONF_SELL_PRICE_SENSOR,
    DOMAIN,
    NIGHT_BUY_WINDOW_END_HOUR,
    NIGHT_BUY_WINDOW_START_HOUR,
)
from .night_buy_window import (
    NightBuyWindowPlan,
    build_night_buy_window_plan,
    night_window_bounds,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

    from .night_buy_window_manager import NightBuyWindowPlanManager

_LOGGER = logging.getLogger(__name__)

DefaultReason = Literal["unavailable", "unreliable"]


class MarketWindowSource(StrEnum):
    """Where a Resolved Market Window came from, in resolution priority order."""

    PLAN = "plan"
    PRICES = "prices"
    CONFIG_ENTITY = "config_entity"
    LEGACY_ENTITY = "legacy_entity"
    DEFAULT = "default"


@dataclass(frozen=True, slots=True, eq=False)
class ResolvedMarketWindow:
    """A Market Window resolved to tz-aware local datetimes and a price.

    Equality and hashing compare the endpoints as instants (UTC): generated
    dataclass equality would compare same-zone datetimes by wall time and
    ignore ``fold``, so two windows of different length in the repeated DST
    hour would compare equal and ``MarketWindows.changed_from`` would miss
    the change.
    """

    start: datetime
    end: datetime
    price: float | None
    source: MarketWindowSource
    reason: DefaultReason | None = None

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Market Window datetimes must be tz-aware")
        if self.end.astimezone(UTC) <= self.start.astimezone(UTC):
            raise ValueError(
                f"Market Window end {self.end} must be after start {self.start}"
            )
        if self.price is not None and not isfinite(self.price):
            raise ValueError(f"Market Window price must be finite, got {self.price}")
        if (self.reason is None) == (self.source is MarketWindowSource.DEFAULT):
            raise ValueError(
                "Market Window reason is set exactly when the source is DEFAULT"
            )

    def _key(
        self,
    ) -> tuple[datetime, datetime, float | None, MarketWindowSource, str | None]:
        return (
            self.start.astimezone(UTC),
            self.end.astimezone(UTC),
            self.price,
            self.source,
            self.reason,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ResolvedMarketWindow):
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    @property
    def hour(self) -> int:
        """Return the local hour the window starts."""
        return self.start.hour

    @property
    def end_hour(self) -> int:
        """Return the local hour the window ends."""
        return self.end.hour

    @property
    def duration_hours(self) -> float:
        """Return the window length in hours."""
        return (
            self.end.astimezone(UTC) - self.start.astimezone(UTC)
        ).total_seconds() / 3600

    @property
    def plan_date(self) -> date:
        """Return the date the window is keyed by: the day it ends on."""
        return self.end.astimezone(self.start.tzinfo).date()

    @property
    def is_fallback(self) -> bool:
        """Return True when this is a Default Market Window, not resolved data."""
        return self.source is MarketWindowSource.DEFAULT

    def start_hour_or(self, default: int) -> int:
        """Return the start hour, or the caller's default for a fallback window."""
        return default if self.is_fallback else self.hour

    def contains(self, now: datetime) -> bool:
        """Return True when `now` falls inside the window (end exclusive).

        Compared as instants: same-zone datetimes would otherwise compare by
        wall time and ignore ``fold`` in the repeated DST hour.
        """
        instant = now.astimezone(UTC)
        return self.start.astimezone(UTC) <= instant < self.end.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class RankedMarketWindow:
    """A Primary Market Window with its optional Secondary Market Window."""

    primary: ResolvedMarketWindow
    secondary: ResolvedMarketWindow | None


@dataclass(frozen=True, slots=True)
class ResolvedHour:
    """A High-Tariff boundary: an hour, not a window."""

    hour: int
    source: MarketWindowSource


@dataclass(frozen=True, slots=True)
class MarketWindows:
    """Every Market Window the decision engine reads, anchored at `now`."""

    now: datetime
    night_buy: ResolvedMarketWindow
    night_buy_completed: ResolvedMarketWindow
    night_buy_after: ResolvedMarketWindow
    day_buy: ResolvedMarketWindow
    day_buy_next: ResolvedMarketWindow
    morning_sell: RankedMarketWindow
    morning_sell_tomorrow: RankedMarketWindow
    evening_sell: RankedMarketWindow
    evening_sell_tomorrow: RankedMarketWindow
    consume: ResolvedMarketWindow
    consume_tomorrow: ResolvedMarketWindow
    morning_sell_buy_reference: ResolvedMarketWindow
    high_tariff_start: ResolvedHour
    high_tariff_end: ResolvedHour

    def changed_from(self, previous: MarketWindows | None) -> frozenset[str]:
        """Return the window fields whose value differs from `previous`."""
        names = [f.name for f in fields(self) if f.name != "now"]
        if previous is None:
            return frozenset(names)
        return frozenset(
            name
            for name in names
            if getattr(self, name) != getattr(previous, name)
        )

    def day_buy_for(self, plan_date: date) -> ResolvedMarketWindow | None:
        """Return the Day Buy Window keyed by `plan_date`, if the snapshot has one."""
        if self.day_buy.plan_date == plan_date:
            return self.day_buy
        if self.day_buy_next.plan_date == plan_date:
            return self.day_buy_next
        return None


# Default Market Window hours: the hours the decision engine used before the
# resolver existed. Day Buy is derived from the High-Tariff start.
DEFAULT_NIGHT_BUY_HOURS: Final = (NIGHT_BUY_WINDOW_START_HOUR, NIGHT_BUY_WINDOW_END_HOUR)
DEFAULT_DAY_BUY_DURATION_HOURS: Final = 2
DEFAULT_MORNING_SELL_HOUR: Final = 7
DEFAULT_EVENING_SELL_HOUR: Final = 17
DEFAULT_CONSUME_HOUR: Final = 12
DEFAULT_HIGH_TARIFF_START_HOUR: Final = 15
DEFAULT_HIGH_TARIFF_END_HOUR: Final = 13

# The hour ranges the ranked sell windows are chosen from.
MORNING_SELL_RANGE_HOURS: Final = (4, 10)
EVENING_SELL_RANGE_HOURS: Final = (16, 22)


def _default_window(
    start: datetime, end: datetime, *, reason: DefaultReason
) -> ResolvedMarketWindow:
    """Build a Default Market Window: no price, source DEFAULT, the given reason."""
    return ResolvedMarketWindow(
        start=start,
        end=end,
        price=None,
        source=MarketWindowSource.DEFAULT,
        reason=reason,
    )


def _default_buy_window(
    now: datetime, start_hour: int, end_hour: int, *, reason: DefaultReason
) -> ResolvedMarketWindow:
    """Build a Default Market Window at today's hours for a buy window."""
    start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    end = now.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if end <= start:
        end += timedelta(days=1)
    if end <= now:
        start += timedelta(days=1)
        end += timedelta(days=1)
    return _default_window(start, end, reason=reason)


def _default_hour_window(
    day: date, hour: int, tz: tzinfo, *, reason: DefaultReason
) -> ResolvedMarketWindow:
    """Build a one-hour Default Market Window at `hour` on `day`."""
    start = datetime.combine(day, time(hour), tzinfo=tz)
    return _default_window(start, start + timedelta(hours=1), reason=reason)


def _default_ranked(
    day: date, hour: int, tz: tzinfo, *, reason: DefaultReason
) -> RankedMarketWindow:
    """A default ranked window has no Secondary Market Window."""
    return RankedMarketWindow(
        primary=_default_hour_window(day, hour, tz, reason=reason), secondary=None
    )


def default_market_windows(
    now: datetime, *, reason: DefaultReason = "unavailable"
) -> MarketWindows:
    """Build a snapshot of Default Market Windows at today's default hours.

    `now` must be in Home Assistant's local time zone (the adapter passes
    `dt_util.now()`); hours are projected in `now`'s zone, never converted.
    """
    night_buy = _default_buy_window(now, *DEFAULT_NIGHT_BUY_HOURS, reason=reason)
    day_buy = _default_buy_window(
        now,
        DEFAULT_HIGH_TARIFF_START_HOUR - DEFAULT_DAY_BUY_DURATION_HOURS,
        DEFAULT_HIGH_TARIFF_START_HOUR,
        reason=reason,
    )
    today = now.date()
    tomorrow = today + timedelta(days=1)
    tz = now.tzinfo
    return MarketWindows(
        now=now,
        night_buy=night_buy,
        night_buy_completed=_default_window(
            datetime.combine(
                today - timedelta(days=1), time(NIGHT_BUY_WINDOW_START_HOUR), tzinfo=tz
            ),
            datetime.combine(today, time(NIGHT_BUY_WINDOW_END_HOUR), tzinfo=tz),
            reason=reason,
        ),
        night_buy_after=_default_window(
            datetime.combine(
                night_buy.plan_date + timedelta(days=1), time.min, tzinfo=tz
            ),
            datetime.combine(
                night_buy.plan_date + timedelta(days=1),
                time(NIGHT_BUY_WINDOW_END_HOUR),
                tzinfo=tz,
            ),
            reason=reason,
        ),
        day_buy=day_buy,
        day_buy_next=_default_window(
            datetime.combine(
                night_buy.plan_date,
                time(DEFAULT_HIGH_TARIFF_START_HOUR - DEFAULT_DAY_BUY_DURATION_HOURS),
                tzinfo=tz,
            ),
            datetime.combine(
                night_buy.plan_date, time(DEFAULT_HIGH_TARIFF_START_HOUR), tzinfo=tz
            ),
            reason=reason,
        ),
        morning_sell=_default_ranked(today, DEFAULT_MORNING_SELL_HOUR, tz, reason=reason),
        morning_sell_tomorrow=_default_ranked(
            tomorrow, DEFAULT_MORNING_SELL_HOUR, tz, reason=reason
        ),
        evening_sell=_default_ranked(today, DEFAULT_EVENING_SELL_HOUR, tz, reason=reason),
        evening_sell_tomorrow=_default_ranked(
            tomorrow, DEFAULT_EVENING_SELL_HOUR, tz, reason=reason
        ),
        consume=_default_hour_window(today, DEFAULT_CONSUME_HOUR, tz, reason=reason),
        consume_tomorrow=_default_hour_window(
            tomorrow, DEFAULT_CONSUME_HOUR, tz, reason=reason
        ),
        morning_sell_buy_reference=_default_window(
            datetime.combine(today, time(DEFAULT_MORNING_SELL_HOUR + 1), tzinfo=tz),
            datetime.combine(today, time(DEFAULT_HIGH_TARIFF_END_HOUR), tzinfo=tz),
            reason=reason,
        ),
        high_tariff_start=ResolvedHour(
            DEFAULT_HIGH_TARIFF_START_HOUR, MarketWindowSource.DEFAULT
        ),
        high_tariff_end=ResolvedHour(
            DEFAULT_HIGH_TARIFF_END_HOUR, MarketWindowSource.DEFAULT
        ),
    )


class MarketWindowResolver(Protocol):
    """The single place EnergyOptimizer asks which Market Windows apply now.

    `windows()` is synchronous, side-effect free and never raises; callers
    read it once at the start of a run and use the snapshot thereafter.
    """

    def windows(self, now: datetime | None = None) -> MarketWindows: ...


class StaticMarketWindowResolver:
    """Resolver returning one fixed snapshot; the test adapter at the seam."""

    def __init__(self, windows: MarketWindows) -> None:
        self._windows = windows

    def windows(
        self,
        now: datetime | None = None,  # NOSONAR S1172: the resolver protocol signature
    ) -> MarketWindows:
        """Return the given snapshot unchanged, whatever `now` is."""
        return self._windows


_UNAVAILABLE_STATES: Final = frozenset({"unknown", "unavailable"})
_TIME_RANGE: Final = re.compile(r"^\s*\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\s*$")

_Span = tuple[datetime, datetime, float | None]
_RankedSpans = tuple[_Span, _Span | None]
_T = TypeVar("_T")
_R = TypeVar("_R")
# A Market Window Source chain: sources in priority order, each answering None
# when it has nothing to supply and raising when its data is invalid.
_Chain = Iterable[tuple[MarketWindowSource, Callable[[], _T | None]]]


def _resolve(
    chain: _Chain[_T],
    *,
    build: Callable[[_T, MarketWindowSource], _R],
    default: Callable[[DefaultReason], _R],
    name: str,
) -> _R:
    """Resolve a value from the first Market Window Source that supplies one.

    A source that raises had data but could not make a valid value of it, so
    the default built after it carries the `unreliable` reason. Nothing
    propagates: a resolver never raises.
    """
    reason: DefaultReason = "unavailable"
    for source, supply in chain:
        try:
            value = supply()
            if value is not None:
                return build(value, source)
        except Exception as err:  # noqa: BLE001 - a resolver never raises
            _LOGGER.warning(
                "%s from %s is invalid (%s), trying the next source", name, source, err
            )
            reason = "unreliable"
    return default(reason)


def _window(span: _Span, source: MarketWindowSource) -> ResolvedMarketWindow:
    start, end, price = span
    return ResolvedMarketWindow(start=start, end=end, price=price, source=source)


def _ranked(spans: _RankedSpans, source: MarketWindowSource) -> RankedMarketWindow:
    primary, secondary = spans
    return RankedMarketWindow(
        primary=_window(primary, source),
        secondary=_window(secondary, source) if secondary is not None else None,
    )


def _split_range(state_value: object) -> tuple[str, str | None]:
    """Split an `HH:MM-HH:MM` entity state into its two times; else (state, None)."""
    raw_value = str(state_value)
    if not _TIME_RANGE.match(raw_value):
        return raw_value, None
    first, second = raw_value.split("-", 1)
    return first.strip(), second.strip()


def _parse_clock(state_value: object) -> time | None:
    """Parse a wall time from a datetime or time entity state."""
    raw_value = str(state_value)
    dt_value = dt_util.parse_datetime(raw_value)
    if dt_value is not None:
        return dt_util.as_local(dt_value).time()
    return dt_util.parse_time(raw_value)


def _parse_hour_number(state_value: object) -> int:
    """Parse a whole hour (0-24) from a numeric entity state."""
    value = float(str(state_value))
    if not isfinite(value) or not 0 <= int(value) <= 24:
        raise ValueError(f"hour {state_value!r} is not a clock hour")
    return int(value)


def _parse_hour(state_value: object) -> int:
    """Parse an hour from a datetime, time or numeric entity state."""
    clock = _parse_clock(state_value)
    return clock.hour if clock is not None else _parse_hour_number(state_value)


def _plan_span(plan: NightBuyWindowPlan | None) -> _Span | None:
    """Project a buy-window plan onto a window span."""
    if plan is None:
        return None
    return plan.start, plan.end, plan.price


def _combined_prices(payload: object) -> list[dict[str, object]] | None:
    """Return a payload's combined price list, or today's and tomorrow's joined."""
    if not isinstance(payload, dict):
        return None
    prices = payload.get("prices")
    if isinstance(prices, list):
        return [item for item in prices if isinstance(item, dict)] or None
    combined: list[dict[str, object]] = []
    seen: set[str] = set()
    for key in ("prices_today", "prices_tomorrow"):
        for item in payload.get(key) or []:
            if isinstance(item, dict) and str(item.get("time")) not in seen:
                seen.add(str(item.get("time")))
                combined.append(item)
    return combined or None


def _day_prices(payload: object, key: str) -> list[dict[str, object]] | None:
    """Return one day's price list from a payload."""
    prices = payload.get(key) if isinstance(payload, dict) else None
    return prices if isinstance(prices, list) else None


def _night_from_prices(
    payload: object, entity_id: str, end_date: date, tz: tzinfo
) -> _Span | None:
    """Plan the night ending on `end_date` from the combined buy prices."""
    prices = _combined_prices(payload)
    if prices is None:
        return None
    return _plan_span(
        build_night_buy_window_plan(prices, entity_id, end_date=end_date, local_tz=tz)
    )


def _ranked_from_prices(
    prices: list[dict[str, object]] | None,
    entity_id: str,
    hours: tuple[int, int],
    now_local: datetime,
) -> _RankedSpans | None:
    """Rank the one-hour sell windows of `now_local`'s day inside `hours`."""
    if prices is None:
        return None
    result = build_ranked_sell_window_result(
        prices,
        entity_id,
        range_start_hour=hours[0],
        range_end_hour=hours[1],
        now_local=now_local,
    )
    if result is None:
        return None
    one_hour = timedelta(hours=1)
    return (
        (result.best_start_local, result.best_start_local + one_hour, result.best_price),
        (
            result.second_best_start_local,
            result.second_best_start_local + one_hour,
            result.second_best_price,
        ),
    )


def _consume_from_prices(
    prices: list[dict[str, object]] | None, entity_id: str, now_local: datetime
) -> _Span | None:
    """Select the cheapest Consume Window of `now_local`'s day from sell prices."""
    if prices is None:
        return None
    result = build_consume_window_result(prices, entity_id, now_local=now_local)
    if result is None:
        return None
    return result.start_local, result.end_local, result.average_price


def _average_buy_from_prices(
    prices: list[dict[str, object]] | None,
    entity_id: str,
    *,
    start_hour: int,
    end_hour: int,
    now_local: datetime,
) -> _Span | None:
    """Average the buy prices of `now_local`'s day over [start_hour, end_hour)."""
    if prices is None:
        return None
    result = build_average_buy_price_result(
        prices, entity_id, start_hour=start_hour, end_hour=end_hour, now_local=now_local
    )
    if result is None:
        return None
    return result.start_local, result.end_local, result.average_price


def _hours_window(
    day: date, start_hour: int, end_hour: int, tz: tzinfo
) -> tuple[datetime, datetime]:
    """Return the span from `start_hour` to `end_hour` on `day`, wrapping past midnight."""
    midnight = datetime.combine(day, time.min, tzinfo=tz)
    start = midnight + timedelta(hours=start_hour)
    end = midnight + timedelta(hours=end_hour)
    if end <= start:
        end += timedelta(days=1)
    return start, end


class CoordinatorMarketWindowResolver:
    """Production resolver over the coordinator, the plan manager and `hass.states`.

    Each snapshot field is resolved by one ordered Market Window Source chain;
    adding a source is a chain position, adding a window is a field plus a chain.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: DataUpdateCoordinator,
        manager: NightBuyWindowPlanManager,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._manager = manager

    def windows(self, now: datetime | None = None) -> MarketWindows:
        """Resolve every Market Window at `now` (default: Home Assistant local now)."""
        current = now or dt_util.now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        current = dt_util.as_local(current)
        tz = current.tzinfo
        today = current.date()
        tomorrow_local = current + timedelta(days=1)
        tomorrow = tomorrow_local.date()
        buy_entity = str(self._entry.data.get(CONF_BUY_PRICE_SENSOR))
        sell_entity = str(self._entry.data.get(CONF_SELL_PRICE_SENSOR))
        data = self._coordinator.data
        payloads = data.get("price_payloads") if isinstance(data, dict) else None
        buy_payload = payloads.get(buy_entity) if isinstance(payloads, dict) else None
        sell_payload = payloads.get(sell_entity) if isinstance(payloads, dict) else None
        sell_today = _day_prices(sell_payload, "prices_today")
        sell_tomorrow = _day_prices(sell_payload, "prices_tomorrow")

        high_tariff_start = self._tariff_hour(
            CONF_HIGH_TARIFF_START_HOUR_SENSOR,
            lowest=0,
            highest=23,
            default=DEFAULT_HIGH_TARIFF_START_HOUR,
            name="High-Tariff start hour",
        )
        high_tariff_end = self._tariff_hour(
            CONF_HIGH_TARIFF_END_HOUR_SENSOR,
            lowest=7,
            highest=24,
            default=DEFAULT_HIGH_TARIFF_END_HOUR,
            name="High-Tariff end hour",
        )

        night_buy = self._plan_window(
            lambda: self._manager.get_active_plan("night", current),
            default=lambda reason: _default_buy_window(
                current, *DEFAULT_NIGHT_BUY_HOURS, reason=reason
            ),
            name="Night Buy Window",
        )
        night_buy_completed = self._plan_window(
            lambda: self._manager.get_plan("night", today),
            default=lambda reason: _default_window(
                *night_window_bounds(today, tz), reason=reason
            ),
            name="completed Night Buy Window",
        )
        after_date = night_buy.plan_date + timedelta(days=1)
        night_buy_after = _resolve(
            [
                (
                    MarketWindowSource.PRICES,
                    lambda: _night_from_prices(buy_payload, buy_entity, after_date, tz),
                )
            ],
            build=_window,
            default=lambda reason: _default_window(
                datetime.combine(after_date, time.min, tzinfo=tz),
                datetime.combine(after_date, time(NIGHT_BUY_WINDOW_END_HOUR), tzinfo=tz),
                reason=reason,
            ),
            name="Night Buy Window after the active one",
        )
        day_buy = self._plan_window(
            lambda: self._manager.get_plan("day", today),
            default=lambda reason: _default_buy_window(
                current,
                (high_tariff_start.hour - DEFAULT_DAY_BUY_DURATION_HOURS) % 24,
                high_tariff_start.hour,
                reason=reason,
            ),
            name="Day Buy Window",
        )
        day_buy_next_end = datetime.combine(
            night_buy.plan_date, time(high_tariff_start.hour), tzinfo=tz
        )
        day_buy_next = self._plan_window(
            lambda: self._manager.get_plan("day", night_buy.plan_date),
            default=lambda reason: _default_window(
                day_buy_next_end - timedelta(hours=DEFAULT_DAY_BUY_DURATION_HOURS),
                day_buy_next_end,
                reason=reason,
            ),
            name="next Day Buy Window",
        )

        morning_sell = self._ranked_sell(
            sell_today,
            sell_entity,
            MORNING_SELL_RANGE_HOURS,
            current,
            default=lambda reason: _default_ranked(
                today, DEFAULT_MORNING_SELL_HOUR, tz, reason=reason
            ),
            legacy=lambda: self._legacy_ranked(
                today, tz, CONF_MORNING_MAX_PRICE_HOUR_SENSOR, CONF_MORNING_MAX_PRICE_SENSOR
            ),
        )
        reference_start_hour = (morning_sell.primary.hour + 1) % 24
        morning_sell_buy_reference = _resolve(
            [
                (
                    MarketWindowSource.PRICES,
                    lambda: _average_buy_from_prices(
                        _day_prices(buy_payload, "prices_today"),
                        buy_entity,
                        start_hour=reference_start_hour,
                        end_hour=high_tariff_end.hour,
                        now_local=current,
                    ),
                )
            ],
            build=_window,
            default=lambda reason: _default_window(
                *_hours_window(today, reference_start_hour, high_tariff_end.hour, tz),
                reason=reason,
            ),
            name="Morning Sell Buy Reference",
        )

        return MarketWindows(
            now=current,
            night_buy=night_buy,
            night_buy_completed=night_buy_completed,
            night_buy_after=night_buy_after,
            day_buy=day_buy,
            day_buy_next=day_buy_next,
            morning_sell=morning_sell,
            morning_sell_tomorrow=self._ranked_sell(
                sell_tomorrow,
                sell_entity,
                MORNING_SELL_RANGE_HOURS,
                tomorrow_local,
                default=lambda reason: _default_ranked(
                    tomorrow, DEFAULT_MORNING_SELL_HOUR, tz, reason=reason
                ),
            ),
            evening_sell=self._ranked_sell(
                sell_today,
                sell_entity,
                EVENING_SELL_RANGE_HOURS,
                current,
                default=lambda reason: _default_ranked(
                    today, DEFAULT_EVENING_SELL_HOUR, tz, reason=reason
                ),
                legacy=lambda: self._legacy_ranked(
                    today,
                    tz,
                    CONF_EVENING_MAX_PRICE_HOUR_SENSOR,
                    CONF_EVENING_MAX_PRICE_SENSOR,
                    CONF_EVENING_SECOND_MAX_PRICE_HOUR_SENSOR,
                    CONF_EVENING_SECOND_MAX_PRICE_SENSOR,
                ),
            ),
            evening_sell_tomorrow=self._ranked_sell(
                sell_tomorrow,
                sell_entity,
                EVENING_SELL_RANGE_HOURS,
                tomorrow_local,
                default=lambda reason: _default_ranked(
                    tomorrow, DEFAULT_EVENING_SELL_HOUR, tz, reason=reason
                ),
            ),
            consume=self._consume(
                sell_today,
                sell_entity,
                current,
                default=lambda reason: _default_hour_window(
                    today, DEFAULT_CONSUME_HOUR, tz, reason=reason
                ),
                legacy=lambda: self._legacy_span(
                    today,
                    tz,
                    CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR,
                    CONF_DAYTIME_MIN_PRICE_SENSOR,
                    whole_hour=False,
                ),
            ),
            consume_tomorrow=self._consume(
                sell_tomorrow,
                sell_entity,
                tomorrow_local,
                default=lambda reason: _default_hour_window(
                    tomorrow, DEFAULT_CONSUME_HOUR, tz, reason=reason
                ),
            ),
            morning_sell_buy_reference=morning_sell_buy_reference,
            high_tariff_start=high_tariff_start,
            high_tariff_end=high_tariff_end,
        )

    # --- one chain per field kind ------------------------------------------

    def _tariff_hour(
        self, config_key: str, *, lowest: int, highest: int, default: int, name: str
    ) -> ResolvedHour:
        """High-Tariff hour: the configured entity inside its range, else the default."""
        return _resolve(
            [
                (
                    MarketWindowSource.CONFIG_ENTITY,
                    lambda: self._config_hour(config_key, lowest=lowest, highest=highest),
                )
            ],
            build=ResolvedHour,
            default=lambda _reason: ResolvedHour(default, MarketWindowSource.DEFAULT),
            name=name,
        )

    def _plan_window(
        self,
        plan: Callable[[], NightBuyWindowPlan | None],
        *,
        default: Callable[[DefaultReason], ResolvedMarketWindow],
        name: str,
    ) -> ResolvedMarketWindow:
        """Buy window: the plan manager's plan, else the default."""
        return _resolve(
            [(MarketWindowSource.PLAN, lambda: _plan_span(plan()))],
            build=_window,
            default=default,
            name=name,
        )

    def _ranked_sell(
        self,
        prices: list[dict[str, object]] | None,
        entity_id: str,
        hours: tuple[int, int],
        now_local: datetime,
        *,
        default: Callable[[DefaultReason], RankedMarketWindow],
        legacy: Callable[[], _RankedSpans | None] | None = None,
    ) -> RankedMarketWindow:
        """Sell Window Ranking: the price payload, the legacy entities, else the default."""
        chain: list[tuple[MarketWindowSource, Callable[[], _RankedSpans | None]]] = [
            (
                MarketWindowSource.PRICES,
                lambda: _ranked_from_prices(prices, entity_id, hours, now_local),
            )
        ]
        if legacy is not None:
            chain.append((MarketWindowSource.LEGACY_ENTITY, legacy))
        return _resolve(chain, build=_ranked, default=default, name="Sell Window Ranking")

    def _consume(
        self,
        prices: list[dict[str, object]] | None,
        entity_id: str,
        now_local: datetime,
        *,
        default: Callable[[DefaultReason], ResolvedMarketWindow],
        legacy: Callable[[], _Span | None] | None = None,
    ) -> ResolvedMarketWindow:
        """Consume Window: the price payload, the legacy entities, else the default."""
        chain: list[tuple[MarketWindowSource, Callable[[], _Span | None]]] = [
            (
                MarketWindowSource.PRICES,
                lambda: _consume_from_prices(prices, entity_id, now_local),
            )
        ]
        if legacy is not None:
            chain.append((MarketWindowSource.LEGACY_ENTITY, legacy))
        return _resolve(chain, build=_window, default=default, name="Consume Window")

    # --- entity reads -------------------------------------------------------

    def _entity_state(self, config_key: str) -> tuple[str | None, object | None]:
        """Return the entity configured under `config_key` and its state, if it has one."""
        entity_id = self._entry.data.get(config_key)
        state = self._hass.states.get(str(entity_id)) if entity_id else None
        if state is None or state.state in _UNAVAILABLE_STATES:
            return entity_id, None
        return entity_id, state.state

    def _config_hour(self, config_key: str, *, lowest: int, highest: int) -> int | None:
        """Read an hour inside [lowest, highest] from the configured entity."""
        _entity_id, raw_hour = self._entity_state(config_key)
        if raw_hour is None:
            return None
        hour = _parse_hour(raw_hour)
        if not lowest <= hour <= highest:
            raise ValueError(f"hour {hour} outside {lowest}-{highest}")
        return hour

    def _legacy_span(
        self,
        day: date,
        tz: tzinfo,
        time_key: str,
        price_key: str,
        *,
        whole_hour: bool = True,
    ) -> _Span | None:
        """A window at a legacy time entity's time, priced by its price entity.

        A sell window is the whole hour the entity names. The Consume Window
        keeps the entity's minutes and, for an `HH:MM-HH:MM` state, its end;
        otherwise a window lasts one hour.
        """
        entity_id, raw_time = self._entity_state(time_key)
        if raw_time is None:
            return None
        first, second = (raw_time, None) if whole_hour else _split_range(raw_time)
        clock = _parse_clock(first)
        if clock is None:
            clock = time(_parse_hour_number(first))
        if whole_hour:
            clock = time(clock.hour)
        start = datetime.combine(day, clock, tzinfo=tz)
        end = start + timedelta(hours=1)
        if second is not None:
            range_end = dt_util.parse_time(second)
            if range_end is None:
                _LOGGER.warning(
                    "Legacy time entity %s range %s has no readable end, window lasts one hour",
                    entity_id,
                    raw_time,
                )
            elif datetime.combine(day, range_end, tzinfo=tz) > start:
                end = datetime.combine(day, range_end, tzinfo=tz)
            else:
                _LOGGER.warning(
                    "Legacy time entity %s range %s ends at or before its start on the same "
                    "day, window lasts one hour",
                    entity_id,
                    raw_time,
                )
        return start, end, self._legacy_price(price_key)

    def _legacy_price(self, price_key: str) -> float | None:
        """The legacy price entity's finite price, or None when it has none."""
        entity_id, raw_price = self._entity_state(price_key)
        try:
            price = float(raw_price) if raw_price is not None else None
        except (TypeError, ValueError):
            price = None
        if price is None or not isfinite(price):
            if raw_price is not None:
                _LOGGER.warning(
                    "Legacy price entity %s has invalid value %s, window keeps no price",
                    entity_id,
                    raw_price,
                )
            return None
        return price

    def _legacy_ranked(
        self,
        day: date,
        tz: tzinfo,
        hour_key: str,
        price_key: str,
        second_hour_key: str | None = None,
        second_price_key: str | None = None,
    ) -> _RankedSpans | None:
        """Legacy Primary Market Window with its optional Secondary Market Window."""
        primary = self._legacy_span(day, tz, hour_key, price_key)
        if primary is None:
            return None
        secondary = None
        if second_hour_key and second_price_key:
            try:
                secondary = self._legacy_span(day, tz, second_hour_key, second_price_key)
            except (TypeError, ValueError) as err:
                _LOGGER.warning(
                    "Legacy second hour entity %s is invalid (%s), no Secondary Market Window",
                    self._entry.data.get(second_hour_key),
                    err,
                )
        return primary, secondary


def market_window_resolver(hass: HomeAssistant, entry_id: str) -> MarketWindowResolver:
    """Return the entry's Market Window Resolver: the only ``hass.data`` lookup for it."""
    return hass.data[DOMAIN][entry_id]["market_windows"]
