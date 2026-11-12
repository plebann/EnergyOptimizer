"""Lifecycle manager for persisted night buy-window plans."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
import asyncio
import logging
from math import isfinite
from typing import Any, TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .const import (
    CONF_BUY_PRICE_SENSOR,
    NIGHT_BUY_WINDOW_PLAN_AFTER_HOUR,
    NIGHT_BUY_WINDOW_ROTATION_HOUR,
    NIGHT_BUY_WINDOW_ROTATION_MINUTE,
    DAY_BUY_WINDOW_EXPANSION_MULTIPLIER,
    STORAGE_KEY_BUY_WINDOW,
    STORAGE_VERSION_BUY_WINDOW,
    NIGHT_BUY_WINDOW_START_HOUR,
)
from .night_buy_window import (
    NightBuyWindowPlan,
    build_night_buy_window_plan,
    night_buy_window_store,
)
from .calculations.price_windows import build_best_buy_window_result
from .helpers import resolve_tariff_end_hour, resolve_tariff_start_hour
from homeassistant.helpers.storage import Store

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class NightBuyWindowPlanManager:
    """Own persisted current/upcoming night and day plans for one entry.

    The historical class name is retained for compatibility with integrations
    and tests which imported it directly.  The manager is now the owner of
    both buy-window kinds.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the plan lifecycle manager."""
        self.hass = hass
        self.entry = entry
        self._current: NightBuyWindowPlan | None = None
        self._upcoming: NightBuyWindowPlan | None = None
        self._day_current: NightBuyWindowPlan | None = None
        self._day_upcoming: NightBuyWindowPlan | None = None
        self._executed_start: str | None = None
        self._lock = asyncio.Lock()

    @property
    def _store(self) -> Store:
        return Store(
            self.hass,
            STORAGE_VERSION_BUY_WINDOW,
            f"{STORAGE_KEY_BUY_WINDOW}.{self.entry.entry_id}",
        )

    async def async_restore(self) -> None:
        """Restore only validated persisted plans."""
        async with self._lock:
            raw = await self._store.async_load()
            if not isinstance(raw, dict):
                # Read the old store once for an in-place migration.
                raw = await night_buy_window_store(
                    self.hass, self.entry.entry_id
                ).async_load()
            if not isinstance(raw, dict):
                return
            night = raw.get("night")
            day = raw.get("day")
            if isinstance(night, dict):
                self._current = NightBuyWindowPlan.from_dict(night.get("window"))
                self._upcoming = NightBuyWindowPlan.from_dict(night.get("next"))
            else:
                # v1 migration: current/upcoming were the night slots.
                self._current = NightBuyWindowPlan.from_dict(raw.get("current"))
                self._upcoming = NightBuyWindowPlan.from_dict(raw.get("upcoming"))
            if isinstance(day, dict):
                self._day_current = NightBuyWindowPlan.from_dict(day.get("window"))
                self._day_upcoming = NightBuyWindowPlan.from_dict(day.get("next"))
            executed_start = raw.get("executed_start_time")
            self._executed_start = (
                str(executed_start) if isinstance(executed_start, str) else None
            )
            if "night" not in raw or "day" not in raw:
                await self._store.async_save(self._snapshot_dict())

    async def _async_save_snapshot(
        self,
        current: NightBuyWindowPlan | None,
        upcoming: NightBuyWindowPlan | None,
        executed_start: str | None,
        day_current: NightBuyWindowPlan | None = None,
        day_upcoming: NightBuyWindowPlan | None = None,
    ) -> None:
        """Persist a candidate lifecycle state."""
        def encode(plan: NightBuyWindowPlan | None) -> dict[str, object] | None:
            return plan.as_dict() if plan is not None else None

        await self._store.async_save(
            {
                "night": {"window": encode(current), "next": encode(upcoming)},
                "day": {"window": encode(day_current), "next": encode(day_upcoming)},
                "executed_start_time": executed_start,
            }
        )

    def _snapshot_dict(self) -> dict[str, object]:
        """Return the version-2 persistent shape."""
        def encode(plan: NightBuyWindowPlan | None) -> dict[str, object] | None:
            return plan.as_dict() if plan is not None else None

        return {
            "night": {"window": encode(self._current), "next": encode(self._upcoming)},
            "day": {"window": encode(self._day_current), "next": encode(self._day_upcoming)},
            "executed_start_time": self._executed_start,
        }

    def _day_plan(
        self,
        prices: list[dict[str, Any]],
        entity_id: str,
        *,
        plan_date: date,
        local_tz: Any,
    ) -> NightBuyWindowPlan | None:
        """Plan the Day Buy Window inside the low-tariff range.

        The range runs from the high-tariff end hour to the high-tariff start
        hour as the configured sensors report them now; a plan for tomorrow
        therefore uses today's hours.
        """
        range_start_hour = resolve_tariff_end_hour(self.hass, self.entry.data)
        range_end_hour = resolve_tariff_start_hour(self.hass, self.entry.data)
        if range_end_hour - range_start_hour < 2:
            _LOGGER.warning(
                "Day buy window range %02d:00-%02d:00 is shorter than two hours, no day plan",
                range_start_hour,
                range_end_hour,
            )
            return None
        expected_hours = set(range(range_start_hour, range_end_hour))
        entries_by_hour: dict[int, dict[str, Any]] = {}
        for raw in prices:
            if not isinstance(raw, dict):
                continue
            try:
                parsed = datetime.fromisoformat(str(raw["time"]).replace("Z", "+00:00"))
                parsed = (
                    parsed.replace(tzinfo=local_tz)
                    if parsed.tzinfo is None
                    else parsed.astimezone(local_tz)
                )
                price = float(raw["price"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                parsed.date() == plan_date
                and parsed.minute == 0
                and parsed.second == 0
                and parsed.microsecond == 0
                and parsed.hour in expected_hours
                and parsed.hour not in entries_by_hour
                and isfinite(price)
            ):
                entries_by_hour[parsed.hour] = raw
        if set(entries_by_hour) != expected_hours:
            return None

        result = build_best_buy_window_result(
            prices,
            entity_id,
            range_key="day",
            range_start_hour=range_start_hour,
            range_end_hour=range_end_hour,
            now_local=datetime.combine(plan_date, time(12), tzinfo=local_tz),
        )
        if result is None:
            return None
        return NightBuyWindowPlan(result.start_local, result.end_local, result.average_price)

    def get_plan(self, kind: str, for_date: date) -> NightBuyWindowPlan | None:
        """Return a plan for its semantic date, regardless of its slot."""
        plans = (
            (self._current, self._upcoming)
            if kind == "night"
            else (self._day_current, self._day_upcoming)
        )
        for plan in plans:
            if plan is not None and plan.plan_date == for_date:
                return plan
        return None

    def get_active_plan(self, kind: str, now: datetime) -> NightBuyWindowPlan | None:
        """Return the earliest plan of a kind that has not yet ended."""
        plans = (
            (self._current, self._upcoming)
            if kind == "night"
            else (self._day_current, self._day_upcoming)
        )
        now_utc = now.astimezone(UTC)
        candidates = [
            plan
            for plan in plans
            if plan is not None and plan.end.astimezone(UTC) > now_utc
        ]
        return min(candidates, key=lambda plan: plan.end, default=None)

    @staticmethod
    def _combined_prices(payload: object) -> list[dict[str, Any]] | None:
        """Use a source-provided combined list or combine today/tomorrow."""
        if not isinstance(payload, dict):
            return None
        prices = payload.get("prices")
        if isinstance(prices, list):
            return [item for item in prices if isinstance(item, dict)]
        combined: list[dict[str, Any]] = []
        seen: set[str] = set()
        for key in ("prices_today", "prices_tomorrow"):
            values = payload.get(key)
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                marker = str(item.get("time"))
                if marker in seen:
                    continue
                seen.add(marker)
                combined.append(item)
        return combined or None

    async def async_reconcile(
        self,
        price_payloads: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> None:
        """Rotate plans and create the first valid post-14:00 plan."""
        async with self._lock:
            await self._async_reconcile_locked(price_payloads, now=now)

    async def _async_reconcile_locked(
        self,
        price_payloads: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> None:
        current_time = now or dt_util.now()
        local_tz = current_time.tzinfo or dt_util.DEFAULT_TIME_ZONE
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=local_tz)

        candidate_current = self._current
        candidate_upcoming = self._upcoming
        candidate_day_current = self._day_current
        candidate_day_upcoming = self._day_upcoming
        candidate_executed_start = self._executed_start
        changed = False
        rotation_time = current_time.replace(
            hour=NIGHT_BUY_WINDOW_ROTATION_HOUR,
            minute=NIGHT_BUY_WINDOW_ROTATION_MINUTE,
            second=0,
            microsecond=0,
        )

        def rotate(
            upcoming: NightBuyWindowPlan | None,
            current: NightBuyWindowPlan | None,
        ) -> tuple[NightBuyWindowPlan | None, NightBuyWindowPlan | None, bool]:
            if upcoming is None:
                return current, None, False
            rotation = datetime.combine(
                upcoming.plan_date,
                time(NIGHT_BUY_WINDOW_ROTATION_HOUR, NIGHT_BUY_WINDOW_ROTATION_MINUTE),
                tzinfo=local_tz,
            )
            if current_time >= rotation:
                return upcoming, None, True
            return current, upcoming, False

        candidate_current, candidate_upcoming, rotated = rotate(
            candidate_upcoming, candidate_current
        )
        changed |= rotated
        candidate_day_current, candidate_day_upcoming, day_rotated = rotate(
            candidate_day_upcoming, candidate_day_current
        )
        changed |= day_rotated
        # A missing upcoming plan must not leave the previous day's plan
        # looking like today's current plan.  The slot is cleared before the
        # best-effort rotation-time recomputation below.
        if current_time >= rotation_time:
            if candidate_current is not None and candidate_current.plan_date != current_time.date():
                candidate_current = None
                changed = True
            if candidate_day_current is not None and candidate_day_current.plan_date != current_time.date():
                candidate_day_current = None
                changed = True
        if rotated or day_rotated:
            candidate_executed_start = None

        if current_time.time() >= time(NIGHT_BUY_WINDOW_PLAN_AFTER_HOUR):
            entity_id = self.entry.data.get(CONF_BUY_PRICE_SENSOR)
            payload = (
                price_payloads.get(str(entity_id))
                if entity_id
                else None
            )
            prices = self._combined_prices(payload)
            if isinstance(prices, list) and candidate_upcoming is None:
                plan = build_night_buy_window_plan(
                    prices,
                    str(entity_id),
                    end_date=current_time.date() + timedelta(days=1),
                    local_tz=local_tz,
                )
                if plan is not None:
                    candidate_upcoming = plan
                    candidate_executed_start = None
                    changed = True
            tomorrow_prices = payload.get("prices_tomorrow") if isinstance(payload, dict) else None
            if isinstance(tomorrow_prices, list) and candidate_day_upcoming is None:
                day_plan = self._day_plan(
                    tomorrow_prices,
                    str(entity_id),
                    plan_date=current_time.date() + timedelta(days=1),
                    local_tz=local_tz,
                )
                if day_plan is not None:
                    candidate_day_upcoming = day_plan
                    changed = True

        # At rotation, recover an empty slot from today's data when possible.
        if current_time >= rotation_time:
            entity_id = self.entry.data.get(CONF_BUY_PRICE_SENSOR)
            payload = price_payloads.get(str(entity_id)) if entity_id else None
            if isinstance(payload, dict):
                if candidate_day_current is None:
                    today_prices = payload.get("prices_today")
                    if isinstance(today_prices, list):
                        candidate_day_current = self._day_plan(
                            today_prices, str(entity_id), plan_date=current_time.date(), local_tz=local_tz
                        )
                        changed |= candidate_day_current is not None
                if candidate_current is None:
                    prices = self._combined_prices(payload)
                    if isinstance(prices, list):
                        candidate_current = build_night_buy_window_plan(
                            prices,
                            str(entity_id),
                            end_date=current_time.date(),
                            local_tz=local_tz,
                        )
                        changed |= candidate_current is not None

        if not changed:
            return

        try:
            try:
                await self._async_save_snapshot(
                    candidate_current,
                    candidate_upcoming,
                    candidate_executed_start,
                    candidate_day_current,
                    candidate_day_upcoming,
                )
            except Exception:
                raise
            self._current, self._upcoming = candidate_current, candidate_upcoming
            self._day_current, self._day_upcoming = candidate_day_current, candidate_day_upcoming
            self._executed_start = candidate_executed_start
        except Exception:
            _LOGGER.exception("Failed to persist night buy-window lifecycle state")
            return

    async def async_claim(self, start: datetime) -> bool:
        """Claim one planned Morning Charge start at most once."""
        async with self._lock:
            if self._upcoming is None or self._upcoming.start != start:
                return False
            serialized_start = start.isoformat()
            if self._executed_start == serialized_start:
                return False
            previous_executed_start = self._executed_start
            self._executed_start = serialized_start
            try:
                await self._async_save_snapshot(
                    self._current,
                    self._upcoming,
                    self._executed_start,
                    self._day_current,
                    self._day_upcoming,
                )
            except Exception:
                self._executed_start = previous_executed_start
                _LOGGER.exception("Failed to persist Morning Charge execution claim")
                return False
            return True

    def get_morning_charge_start(self) -> datetime | None:
        """Return the validated upcoming plan start."""
        return self._upcoming.start if self._upcoming is not None else None

    def missed_morning_charge_is_eligible(self, now: datetime) -> bool:
        """Return whether a missed start remains inside its plan."""
        if self._upcoming is None:
            return False
        now_utc = now.astimezone(UTC)
        return (
            self._upcoming.start.astimezone(UTC)
            <= now_utc
            < self._upcoming.end.astimezone(UTC)
        )

    def snapshot(self) -> dict[str, dict[str, object] | None]:
        """Return the serializable coordinator projection."""
        snapshot = self._snapshot_dict()
        # Keep the old projection during migration of consumers outside this
        # integration; the new slots are authoritative.
        snapshot["current"] = snapshot["night"]["window"]
        snapshot["upcoming"] = snapshot["night"]["next"]
        return snapshot


# New semantic name; retain the old export for backwards compatibility.
BuyWindowPlanManager = NightBuyWindowPlanManager
