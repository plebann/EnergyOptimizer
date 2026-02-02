"""Action scheduler for Energy Optimizer."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from homeassistant.helpers.event import async_track_time_change

from ..decision_engine.evening_behavior import async_run_evening_behavior
from ..decision_engine.morning_charge import async_run_morning_charge

if TYPE_CHECKING:
    from datetime import datetime
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class ActionScheduler:
    """Scheduler for fixed and dynamic actions."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the scheduler."""
        self.hass = hass
        self.entry = entry
        self._listeners: list[Callable[[], None]] = []

    def start(self) -> None:
        """Start scheduling fixed actions."""
        self._listeners.append(
            async_track_time_change(
                self.hass, self._handle_morning_charge, hour=4, minute=0, second=0
            )
        )
        self._listeners.append(
            async_track_time_change(
                self.hass, self._handle_evening_behavior, hour=22, minute=0, second=0
            )
        )

        _LOGGER.info("Energy Optimizer scheduler started for entry %s", self.entry.entry_id)

    def stop(self) -> None:
        """Stop all scheduled listeners."""
        for remove_listener in self._listeners:
            remove_listener()
        self._listeners.clear()

    async def _handle_morning_charge(self, now: datetime) -> None:
        """Run morning charge routine at 04:00."""
        _LOGGER.info("Scheduler triggering morning grid charge")
        await async_run_morning_charge(
            self.hass,
            entry_id=self.entry.entry_id,
        )

    async def _handle_evening_behavior(self, now: datetime) -> None:
        """Run evening behavior routine at 22:00."""
        _LOGGER.info("Scheduler triggering evening behavior")
        await async_run_evening_behavior(
            self.hass,
            entry_id=self.entry.entry_id,
        )
