"""Lifecycle manager for persisted night buy-window plans."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
import logging
from typing import Any, TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .const import (
    CONF_BUY_PRICE_SENSOR,
    NIGHT_BUY_WINDOW_PLAN_AFTER_HOUR,
    NIGHT_BUY_WINDOW_ROTATION_HOUR,
    NIGHT_BUY_WINDOW_ROTATION_MINUTE,
)
from .night_buy_window import (
    NightBuyWindowPlan,
    build_night_buy_window_plan,
    night_buy_window_store,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class NightBuyWindowPlanManager:
    """Own persisted current/upcoming night plans for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the plan lifecycle manager."""
        self.hass = hass
        self.entry = entry
        self._current: NightBuyWindowPlan | None = None
        self._upcoming: NightBuyWindowPlan | None = None
        self._executed_start: str | None = None

    async def async_restore(self) -> None:
        """Restore only validated persisted plans."""
        raw = await night_buy_window_store(self.hass, self.entry.entry_id).async_load()
        if not isinstance(raw, dict):
            return
        self._current = NightBuyWindowPlan.from_dict(raw.get("current"))
        self._upcoming = NightBuyWindowPlan.from_dict(raw.get("upcoming"))
        executed_start = raw.get("executed_start_time")
        self._executed_start = (
            str(executed_start) if isinstance(executed_start, str) else None
        )

    async def _async_save_snapshot(
        self,
        current: NightBuyWindowPlan | None,
        upcoming: NightBuyWindowPlan | None,
        executed_start: str | None,
    ) -> None:
        """Persist a candidate lifecycle state."""
        await night_buy_window_store(self.hass, self.entry.entry_id).async_save(
            {
                "current": current.as_dict() if current is not None else None,
                "upcoming": upcoming.as_dict() if upcoming is not None else None,
                "executed_start_time": executed_start,
            }
        )

    async def async_reconcile(
        self,
        price_payloads: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> None:
        """Rotate plans and create the first valid post-14:00 plan."""
        current_time = now or dt_util.now()
        local_tz = current_time.tzinfo or dt_util.DEFAULT_TIME_ZONE
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=local_tz)

        candidate_current = self._current
        candidate_upcoming = self._upcoming
        candidate_executed_start = self._executed_start
        changed = False
        rotation_time = current_time.replace(
            hour=NIGHT_BUY_WINDOW_ROTATION_HOUR,
            minute=NIGHT_BUY_WINDOW_ROTATION_MINUTE,
            second=0,
            microsecond=0,
        )

        if candidate_upcoming is not None and current_time >= rotation_time:
            upcoming_end = candidate_upcoming.end.astimezone(local_tz)
            if upcoming_end.date() < current_time.date():
                if (
                    candidate_current is None
                    or candidate_upcoming.end.astimezone(UTC)
                    > candidate_current.end.astimezone(UTC)
                ):
                    candidate_current = candidate_upcoming
                candidate_upcoming = None
                candidate_executed_start = None
                changed = True
            elif upcoming_end.date() == current_time.date():
                candidate_current = candidate_upcoming
                candidate_upcoming = None
                candidate_executed_start = None
                changed = True

        if (
            current_time.time() >= time(NIGHT_BUY_WINDOW_PLAN_AFTER_HOUR)
            and candidate_upcoming is None
        ):
            entity_id = self.entry.data.get(CONF_BUY_PRICE_SENSOR)
            payload = (
                price_payloads.get(str(entity_id))
                if entity_id
                else None
            )
            prices = payload.get("prices") if isinstance(payload, dict) else None
            if isinstance(prices, list):
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

        if not changed:
            return

        try:
            await self._async_save_snapshot(
                candidate_current,
                candidate_upcoming,
                candidate_executed_start,
            )
        except Exception:
            _LOGGER.exception("Failed to persist night buy-window lifecycle state")
            return

        self._current = candidate_current
        self._upcoming = candidate_upcoming
        self._executed_start = candidate_executed_start

    async def async_claim(self, start: datetime) -> bool:
        """Claim one planned Morning Charge start at most once."""
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
        return {
            "current": self._current.as_dict() if self._current is not None else None,
            "upcoming": self._upcoming.as_dict() if self._upcoming is not None else None,
        }
