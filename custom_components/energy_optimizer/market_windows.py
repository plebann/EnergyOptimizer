"""Market Window Resolver vocabulary: resolved windows, snapshot and adapters."""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum
from typing import Final, Literal, Protocol

from .const import NIGHT_BUY_WINDOW_END_HOUR, NIGHT_BUY_WINDOW_START_HOUR

DefaultReason = Literal["unavailable", "unreliable"]


class MarketWindowSource(StrEnum):
    """Where a Resolved Market Window came from, in resolution priority order."""

    PLAN = "plan"
    PRICES = "prices"
    CONFIG_ENTITY = "config_entity"
    LEGACY_ENTITY = "legacy_entity"
    DEFAULT = "default"


@dataclass(frozen=True, slots=True)
class ResolvedMarketWindow:
    """A Market Window resolved to tz-aware local datetimes and a price."""

    start: datetime
    end: datetime
    price: float | None
    source: MarketWindowSource
    reason: DefaultReason | None = None

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Market Window datetimes must be tz-aware")
        if self.end <= self.start:
            raise ValueError(
                f"Market Window end {self.end} must be after start {self.start}"
            )
        if (self.reason is None) == (self.source is MarketWindowSource.DEFAULT):
            raise ValueError(
                "Market Window reason is set exactly when the source is DEFAULT"
            )

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
        return (self.end - self.start).total_seconds() / 3600

    @property
    def plan_date(self) -> date:
        """Return the date the window is keyed by: the day it ends on."""
        return self.end.date()

    @property
    def is_fallback(self) -> bool:
        """Return True when this is a Default Market Window, not resolved data."""
        return self.source is MarketWindowSource.DEFAULT

    def start_hour_or(self, default: int) -> int:
        """Return the start hour, or the caller's default for a fallback window."""
        return default if self.is_fallback else self.hour

    def contains(self, now: datetime) -> bool:
        """Return True when `now` falls inside the window (end exclusive)."""
        return self.start <= now < self.end


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
    return ResolvedMarketWindow(
        start=start,
        end=end,
        price=None,
        source=MarketWindowSource.DEFAULT,
        reason=reason,
    )


def _default_hour_window(
    day: date, hour: int, tz: tzinfo, *, reason: DefaultReason
) -> ResolvedMarketWindow:
    """Build a one-hour Default Market Window at `hour` on `day`."""
    start = datetime.combine(day, time(hour), tzinfo=tz)
    return ResolvedMarketWindow(
        start=start,
        end=start + timedelta(hours=1),
        price=None,
        source=MarketWindowSource.DEFAULT,
        reason=reason,
    )


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
    """Build a snapshot of Default Market Windows at today's default hours."""
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
        night_buy_completed=night_buy,
        night_buy_after=ResolvedMarketWindow(
            start=datetime.combine(
                night_buy.plan_date + timedelta(days=1), time.min, tzinfo=tz
            ),
            end=datetime.combine(
                night_buy.plan_date + timedelta(days=1),
                time(NIGHT_BUY_WINDOW_END_HOUR),
                tzinfo=tz,
            ),
            price=None,
            source=MarketWindowSource.DEFAULT,
            reason=reason,
        ),
        day_buy=day_buy,
        day_buy_next=day_buy,
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
        morning_sell_buy_reference=ResolvedMarketWindow(
            start=datetime.combine(today, time(DEFAULT_MORNING_SELL_HOUR + 1), tzinfo=tz),
            end=datetime.combine(today, time(DEFAULT_HIGH_TARIFF_END_HOUR), tzinfo=tz),
            price=None,
            source=MarketWindowSource.DEFAULT,
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

    def windows(self, now: datetime | None = None) -> MarketWindows:
        """Return the given snapshot unchanged, whatever `now` is."""
        return self._windows
