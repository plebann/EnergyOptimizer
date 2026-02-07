"""Action scheduler for Energy Optimizer."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change

from ..decision_engine.evening_behavior import async_run_evening_behavior
from ..decision_engine.afternoon_charge import async_run_afternoon_charge
from ..decision_engine.morning_charge import async_run_morning_charge
from ..helpers import resolve_tariff_end_hour
from ..const import CONF_TARIFF_END_HOUR_SENSOR

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
        self._afternoon_listener: Callable[[], None] | None = None

    def start(self) -> None:
        """Start scheduling fixed actions."""
        self._listeners.append(
            async_track_time_change(
                self.hass, self._handle_morning_charge, hour=4, minute=0, second=0
            )
        )
        self._schedule_afternoon_charge()
        self._listeners.append(
            async_track_time_change(
                self.hass, self._handle_evening_behavior, hour=22, minute=0, second=0
            )
        )

        tariff_end_entity = self.entry.data.get(CONF_TARIFF_END_HOUR_SENSOR)
        if tariff_end_entity:
            self._listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [str(tariff_end_entity)],
                    self._handle_tariff_end_change,
                )
            )

        _LOGGER.info("Energy Optimizer scheduler started for entry %s", self.entry.entry_id)

    def stop(self) -> None:
        """Stop all scheduled listeners."""
        for remove_listener in self._listeners:
            remove_listener()
        self._listeners.clear()
        if self._afternoon_listener is not None:
            self._afternoon_listener()
            self._afternoon_listener = None

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

    async def _handle_afternoon_charge(self, now: datetime) -> None:
        """Run afternoon charge routine at tariff end hour."""
        _LOGGER.info("Scheduler triggering afternoon charge")
        await async_run_afternoon_charge(
            self.hass,
            entry_id=self.entry.entry_id,
        )

    async def _handle_tariff_end_change(self, event) -> None:
        """Reschedule afternoon charge when tariff end hour changes."""
        self._schedule_afternoon_charge()

    def _schedule_afternoon_charge(self) -> None:
        """Schedule afternoon charge at current tariff end hour."""
        if self._afternoon_listener is not None:
            self._afternoon_listener()
            self._afternoon_listener = None

        hour = resolve_tariff_end_hour(self.hass, self.entry.data)
        self._afternoon_listener = async_track_time_change(
            self.hass,
            self._handle_afternoon_charge,
            hour=hour,
            minute=0,
            second=0,
        )
