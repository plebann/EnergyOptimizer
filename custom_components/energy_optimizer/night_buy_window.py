"""Persistent planning primitives for the 22:00--06:00 night buy window."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from math import isfinite
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from .calculations.price_windows import (
    BuyWindowResult,
    build_best_buy_window_result_for_period,
)
from .const import (
    NIGHT_BUY_WINDOW_END_HOUR,
    NIGHT_BUY_WINDOW_EXPANSION_MULTIPLIER,
    NIGHT_BUY_WINDOW_START_HOUR,
    STORAGE_KEY_NIGHT_BUY_WINDOW,
    STORAGE_VERSION_NIGHT_BUY_WINDOW,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@dataclass(frozen=True, slots=True)
class NightBuyWindowPlan:
    """A validated plan for one night ending at 06:00 local time."""

    start: datetime
    end: datetime
    price: float

    @property
    def duration_hours(self) -> int:
        """Return the whole-hour duration represented by the plan."""
        return int(
            (
                self.end.astimezone(UTC) - self.start.astimezone(UTC)
            ).total_seconds()
            // 3600
        )

    def as_dict(self) -> dict[str, object]:
        """Serialize the plan for coordinator data and HA storage."""
        return {
            "start_time": self.start.isoformat(),
            "end_time": self.end.isoformat(),
            "duration_hours": self.duration_hours,
            "price": self.price,
            "validated_complete": True,
        }

    @classmethod
    def from_dict(cls, raw: object) -> "NightBuyWindowPlan | None":
        """Deserialize only plans explicitly saved from complete input data."""
        if not isinstance(raw, dict) or raw.get("validated_complete") is not True:
            return None
        try:
            start = datetime.fromisoformat(str(raw["start_time"]))
            end = datetime.fromisoformat(str(raw["end_time"]))
            price = float(raw["price"])
            duration_hours = int(raw["duration_hours"])
        except (KeyError, TypeError, ValueError):
            return None
        if (
            not isfinite(price)
            or start.tzinfo is None
            or end.tzinfo is None
            or end <= start
            or duration_hours <= 0
        ):
            return None
        elapsed_hours = int(
            (
                end.astimezone(UTC) - start.astimezone(UTC)
            ).total_seconds()
            // 3600
        )
        if duration_hours != elapsed_hours:
            return None
        return cls(start=start, end=end, price=price)


def night_window_bounds(end_date: date, local_tz: tzinfo) -> tuple[datetime, datetime]:
    """Return the absolute 22:00 previous-day through 06:00 bounds."""
    end = datetime.combine(end_date, time(NIGHT_BUY_WINDOW_END_HOUR), tzinfo=local_tz)
    start = datetime.combine(
        end_date - timedelta(days=1),
        time(NIGHT_BUY_WINDOW_START_HOUR),
        tzinfo=local_tz,
    )
    return start, end


def build_night_buy_window_plan(
    prices: list[dict[str, Any]],
    entity_id: str,
    *,
    end_date: date,
    local_tz: tzinfo,
) -> NightBuyWindowPlan | None:
    """Build a validated night plan from a complete combined price payload."""
    range_start, range_end = night_window_bounds(end_date, local_tz)
    range_start_utc = range_start.astimezone(UTC)
    range_end_utc = range_end.astimezone(UTC)
    expected_starts = {
        range_start_utc + timedelta(hours=hour)
        for hour in range(
            int((range_end_utc - range_start_utc).total_seconds() // 3600)
        )
    }
    seen_starts: set[datetime] = set()
    for raw_entry in prices:
        if not isinstance(raw_entry, dict):
            continue
        raw_time = raw_entry.get("time")
        try:
            if isinstance(raw_time, datetime):
                parsed = raw_time
            else:
                parsed = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=local_tz)
        else:
            parsed = parsed.astimezone(local_tz)
        parsed_utc = parsed.astimezone(UTC)
        if parsed_utc not in expected_starts:
            continue
        try:
            price = float(raw_entry.get("price"))
        except (TypeError, ValueError):
            return None
        if not isfinite(price) or parsed_utc in seen_starts:
            return None
        seen_starts.add(parsed_utc)
    if seen_starts != expected_starts:
        return None

    result: BuyWindowResult | None = build_best_buy_window_result_for_period(
        prices,
        entity_id,
        range_start=range_start,
        range_end=range_end,
        expansion_multiplier=NIGHT_BUY_WINDOW_EXPANSION_MULTIPLIER,
    )
    if result is None:
        return None
    return NightBuyWindowPlan(
        start=result.start_local,
        end=result.end_local,
        price=result.average_price,
    )


def night_buy_window_store(hass: HomeAssistant, entry_id: str) -> Store:
    """Return the versioned persistent store for an entry's night plans."""
    return Store(
        hass,
        STORAGE_VERSION_NIGHT_BUY_WINDOW,
        f"{STORAGE_KEY_NIGHT_BUY_WINDOW}.{entry_id}",
    )
