"""Market Window Resolver vocabulary: resolved windows, snapshot and adapters."""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
from enum import StrEnum
from typing import Literal


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
    reason: Literal["unavailable", "unreliable"] | None = None

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
