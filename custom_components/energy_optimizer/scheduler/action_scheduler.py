"""Action scheduler for Energy Optimizer."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change

from ..decision_engine.evening_sell import async_run_evening_sell
from ..decision_engine.morning_sell import async_run_morning_sell
from ..decision_engine.evening_behavior import async_run_evening_behavior
from ..decision_engine.afternoon_charge import async_run_afternoon_charge
from ..decision_engine.morning_charge import async_run_morning_charge
from ..helpers import (
    resolve_evening_max_price_hour,
    resolve_morning_max_price_hour,
    resolve_tariff_end_hour,
)
from ..const import (
    CONF_EVENING_MAX_PRICE_HOUR_SENSOR,
    CONF_MORNING_MAX_PRICE_HOUR_SENSOR,
    CONF_TARIFF_END_HOUR_SENSOR,
)

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
        self._morning_sell_listener: Callable[[], None] | None = None
        self._evening_sell_listener: Callable[[], None] | None = None

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
        self._schedule_morning_sell()
        self._schedule_evening_sell()

        tariff_end_entity = self.entry.data.get(CONF_TARIFF_END_HOUR_SENSOR)
        if tariff_end_entity:
            self._listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [str(tariff_end_entity)],
                    self._handle_tariff_end_change,
                )
            )

        evening_peak_hour_entity = self.entry.data.get(CONF_EVENING_MAX_PRICE_HOUR_SENSOR)
        if evening_peak_hour_entity:
            self._listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [str(evening_peak_hour_entity)],
                    self._handle_evening_peak_hour_change,
                )
            )

        morning_peak_hour_entity = self.entry.data.get(CONF_MORNING_MAX_PRICE_HOUR_SENSOR)
        if morning_peak_hour_entity:
            self._listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [str(morning_peak_hour_entity)],
                    self._handle_morning_peak_hour_change,
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
        if self._morning_sell_listener is not None:
            self._morning_sell_listener()
            self._morning_sell_listener = None
        if self._evening_sell_listener is not None:
            self._evening_sell_listener()
            self._evening_sell_listener = None

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

    async def _handle_evening_sell(self, now: datetime) -> None:
        """Run evening peak sell routine at configured peak hour."""
        _LOGGER.info("Scheduler triggering evening peak sell")
        await async_run_evening_sell(
            self.hass,
            entry_id=self.entry.entry_id,
        )

    async def _handle_morning_sell(self, now: datetime) -> None:
        """Run morning peak sell routine at configured peak hour."""
        _LOGGER.info("Scheduler triggering morning peak sell")
        await async_run_morning_sell(
            self.hass,
            entry_id=self.entry.entry_id,
        )

    async def _handle_tariff_end_change(self, event) -> None:
        """Reschedule afternoon charge when tariff end hour changes."""
        self._schedule_afternoon_charge()

    async def _handle_evening_peak_hour_change(self, event) -> None:
        """Reschedule evening peak sell when peak hour changes."""
        self._schedule_evening_sell()

    async def _handle_morning_peak_hour_change(self, event) -> None:
        """Reschedule morning peak sell when peak hour changes."""
        self._schedule_morning_sell()

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

    def _schedule_evening_sell(self) -> None:
        """Schedule evening peak sell at configured evening max price hour."""
        if self._evening_sell_listener is not None:
            self._evening_sell_listener()
            self._evening_sell_listener = None

        hour = resolve_evening_max_price_hour(self.hass, self.entry.data, default_hour=17)
        self._evening_sell_listener = async_track_time_change(
            self.hass,
            self._handle_evening_sell,
            hour=hour,
            minute=0,
            second=0,
        )

    def _schedule_morning_sell(self) -> None:
        """Schedule morning peak sell at configured morning max price hour."""
        if self._morning_sell_listener is not None:
            self._morning_sell_listener()
            self._morning_sell_listener = None

        hour = resolve_morning_max_price_hour(self.hass, self.entry.data, default_hour=7)
        self._morning_sell_listener = async_track_time_change(
            self.hass,
            self._handle_morning_sell,
            hour=hour,
            minute=0,
            second=0,
        )
