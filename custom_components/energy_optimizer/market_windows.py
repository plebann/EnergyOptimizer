"""Market Window Resolver vocabulary: resolved windows, snapshot and adapters."""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from enum import StrEnum
from math import isfinite
from typing import TYPE_CHECKING, Final, Literal, Protocol

from homeassistant.util import dt as dt_util

from .const import DOMAIN, NIGHT_BUY_WINDOW_END_HOUR, NIGHT_BUY_WINDOW_START_HOUR

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

    from .night_buy_window_manager import NightBuyWindowPlanManager

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


class CoordinatorMarketWindowResolver:
    """Production resolver over the coordinator, the plan manager and `hass.states`."""

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
        return default_market_windows(current)


def market_window_resolver(hass: HomeAssistant, entry_id: str) -> MarketWindowResolver:
    """Return the entry's Market Window Resolver: the only ``hass.data`` lookup for it."""
    return hass.data[DOMAIN][entry_id]["market_windows"]
