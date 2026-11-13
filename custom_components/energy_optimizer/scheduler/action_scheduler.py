"""Action scheduler for Energy Optimizer."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_sunrise,
    async_track_sunset,
    async_track_time_change,
)
from homeassistant.util import dt as dt_util

from ..const import (
    AUTOMATION_AFTERNOON_CHARGE,
    AUTOMATION_EVENING_BEHAVIOR,
    AUTOMATION_EVENING_SELL,
    AUTOMATION_EXPORT_BLOCK_CONTROL,
    AUTOMATION_MORNING_CHARGE,
    AUTOMATION_MORNING_SELL,
    AUTOMATION_SOLAR_CHARGE_BLOCK,
    CONF_BEV_CHARGING_BINARY_SENSOR,
    CONF_HIGH_TARIFF_START_HOUR_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_PROG4_TIME_START_ENTITY,
    CONF_SELL_PRICE_SENSOR,
    DOMAIN,
    EVENING_BEHAVIOR_PREPARE_HOUR,
    EVENING_BEHAVIOR_PREPARE_MINUTE,
    NIGHT_BUY_WINDOW_ROTATION_HOUR,
    NIGHT_BUY_WINDOW_ROTATION_MINUTE,
    NIGHT_BUY_WINDOW_START_HOUR,
    SUN_ABOVE_HORIZON,
    SUN_ENTITY,
)
from ..decision_engine.evening_sell import async_run_evening_sell
from ..decision_engine.morning_sell import async_run_morning_sell
from ..decision_engine.evening_behavior import async_run_evening_behavior
from ..decision_engine.afternoon_charge import async_run_afternoon_charge
from ..decision_engine.morning_charge import async_run_morning_charge
from ..decision_engine.program4_solar_reset import async_run_program4_solar_reset
from ..decision_engine.daytime_min_price_restore import async_run_daytime_min_price_restore
from ..decision_engine.solar_charge_block import async_run_solar_charge_block
from ..decision_engine.export_block_control import (
    async_restore_export_block_control,
    async_run_export_block_control,
)
from ..service_handlers.sell_restore import (
    async_check_pending_sell_restore,
    async_handle_sell_restore,
)
from ..service_handlers.charge_completion import (
    async_restore_charge_completions,
    cancel_charge_completion_listeners,
)
from ..market_windows import MarketWindowResolver, MarketWindows
from ..helpers import (
    resolve_prog4_start_time,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# Window field -> the reschedule methods its change triggers.
_WINDOW_RESCHEDULES: dict[str, tuple[str, ...]] = {
    "night_buy": ("_schedule_morning_charge",),
    "day_buy": ("_schedule_afternoon_charge", "_schedule_program4_solar_reset"),
    "high_tariff_start": (
        "_schedule_afternoon_charge",
        "_schedule_program4_solar_reset",
    ),
    "morning_sell": ("_schedule_morning_sell", "_schedule_sell_restores"),
    "evening_sell": ("_schedule_evening_sell", "_schedule_sell_restores"),
    "consume": ("_schedule_daytime_min_price_restore",),
}


class ActionScheduler:
    """Scheduler for fixed and dynamic actions."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: Any | None = None,
        resolver: MarketWindowResolver | None = None,
    ) -> None:
        """Initialize the scheduler."""
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator or (
            hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("coordinator")
        )
        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        self._resolver = resolver or entry_data.get("market_windows")
        self._windows: MarketWindows | None = (
            self._resolver.windows() if self._resolver is not None else None
        )
        self._listeners: list[Callable[[], None]] = []
        self._morning_charge_listener: Callable[[], None] | None = None
        self._afternoon_listener: Callable[[], None] | None = None
        self._program4_solar_reset_listener: Callable[[], None] | None = None
        self._morning_sell_listener: Callable[[], None] | None = None
        self._evening_sell_listener: Callable[[], None] | None = None
        self._evening_sell_second_listener: Callable[[], None] | None = None
        self._morning_restore_listener: Callable[[], None] | None = None
        self._evening_restore_listener: Callable[[], None] | None = None
        self._daytime_min_price_listener: Callable[[], None] | None = None
        self._price_hourly_listener: Callable[[], None] | None = None
        self._sunrise_listener: Callable[[], None] | None = None
        self._sunset_listener: Callable[[], None] | None = None
        self._charge_completion_restore_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    def _create_task(self, coro) -> asyncio.Task[Any] | None:
        """Create and own a scheduler background task until it finishes."""
        task = self.hass.async_create_task(coro)
        if task is None:
            coro.close()
            return None
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def start(self) -> None:
        """Start scheduling fixed actions."""
        self._schedule_afternoon_charge()
        self._schedule_program4_solar_reset()
        self._listeners.append(
            async_track_time_change(
                self.hass,
                self._handle_evening_behavior,
                hour=EVENING_BEHAVIOR_PREPARE_HOUR,
                minute=EVENING_BEHAVIOR_PREPARE_MINUTE,
                second=1,
            )
        )
        self._listeners.append(
            async_track_time_change(
                self.hass,
                self._handle_daily_schedule_refresh,
                hour=0,
                minute=0,
                second=1,
            )
        )
        self._schedule_morning_sell()
        self._schedule_evening_sell()
        self._schedule_sell_restores()
        self._schedule_daytime_min_price_restore()
        entry_data = self.hass.data.setdefault(DOMAIN, {}).setdefault(
            self.entry.entry_id,
            {},
        )
        entry_data["charge_completion_snapshot_callback"] = (
            self._publish_schedule_snapshot
        )
        self._charge_completion_restore_task = self._create_task(
            self._restore_completions_then_schedule_morning_charge()
        )

        if self.coordinator is not None:
            remove_coordinator_listener = self.coordinator.async_add_listener(
                self._handle_coordinator_update
            )
            if callable(remove_coordinator_listener):
                self._listeners.append(remove_coordinator_listener)

        self._sunrise_listener = async_track_sunrise(
            self.hass,
            self._handle_sunrise,
        )
        self._sunset_listener = async_track_sunset(
            self.hass,
            self._handle_sunset,
        )
        if self._is_sun_above_horizon():
            self._start_price_hourly_listener()
        else:
            _LOGGER.debug(
                "Price-driven actions: sun not above horizon at startup — hourly trigger inactive"
            )

        bev_charging_entity = self.entry.data.get(CONF_BEV_CHARGING_BINARY_SENSOR)
        if bev_charging_entity:
            self._listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [str(bev_charging_entity)],
                    self._handle_bev_charging_change,
                )
            )

        tariff_start_entity = self.entry.data.get(CONF_HIGH_TARIFF_START_HOUR_SENSOR)
        if tariff_start_entity:
            self._listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [str(tariff_start_entity)],
                    self._handle_tariff_start_change,
                )
            )

        self._listeners.append(
            async_track_time_change(
                self.hass,
                self._handle_night_buy_window_rotation,
                hour=NIGHT_BUY_WINDOW_ROTATION_HOUR,
                minute=NIGHT_BUY_WINDOW_ROTATION_MINUTE,
                second=0,
            )
        )

        program4_start_entity = self.entry.data.get(CONF_PROG4_TIME_START_ENTITY)
        if program4_start_entity:
            self._listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [str(program4_start_entity)],
                    self._handle_program4_start_time_change,
                )
            )

        self._publish_schedule_snapshot()
        _LOGGER.info("Energy Optimizer scheduler started for entry %s", self.entry.entry_id)

    async def _restore_completions_then_schedule_morning_charge(self) -> None:
        """Restore completions before scheduling a possible startup charge."""
        await async_restore_charge_completions(self.hass, self.entry)
        self._reschedule_changed_windows("_schedule_morning_charge")

    def stop(self) -> None:
        """Stop all scheduled listeners."""
        for remove_listener in self._listeners:
            remove_listener()
        self._listeners.clear()
        if self._morning_charge_listener is not None:
            self._morning_charge_listener()
            self._morning_charge_listener = None
        if self._afternoon_listener is not None:
            self._afternoon_listener()
            self._afternoon_listener = None
        if self._program4_solar_reset_listener is not None:
            self._program4_solar_reset_listener()
            self._program4_solar_reset_listener = None
        if self._morning_sell_listener is not None:
            self._morning_sell_listener()
            self._morning_sell_listener = None
        if self._evening_sell_listener is not None:
            self._evening_sell_listener()
            self._evening_sell_listener = None
        if self._evening_sell_second_listener is not None:
            self._evening_sell_second_listener()
            self._evening_sell_second_listener = None
        if self._morning_restore_listener is not None:
            self._morning_restore_listener()
            self._morning_restore_listener = None
        if self._evening_restore_listener is not None:
            self._evening_restore_listener()
            self._evening_restore_listener = None
        if self._daytime_min_price_listener is not None:
            self._daytime_min_price_listener()
            self._daytime_min_price_listener = None
        self._stop_price_hourly_listener()
        if self._sunrise_listener is not None:
            self._sunrise_listener()
            self._sunrise_listener = None
        if self._sunset_listener is not None:
            self._sunset_listener()
            self._sunset_listener = None
        if self._charge_completion_restore_task is not None:
            self._charge_completion_restore_task.cancel()
            self._charge_completion_restore_task = None
        for task in tuple(self._tasks):
            task.cancel()
        self._tasks.clear()
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        if isinstance(entry_data, dict):
            entry_data.pop("charge_completion_snapshot_callback", None)
        cancel_charge_completion_listeners(self.hass, self.entry)
        self._clear_schedule_snapshot()

    def _automation_enabled(self, key: str) -> bool:
        """Return whether a scheduler-only automation is enabled."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        switches = entry_data.get("automation_switches", {}) if isinstance(entry_data, dict) else {}
        switch = switches.get(key) if isinstance(switches, dict) else None
        return switch is None or bool(switch.is_on)

    def _skip_if_automation_disabled(self, key: str) -> bool:
        """Log and signal that a disabled automation must not run."""
        if self._automation_enabled(key):
            return False
        _LOGGER.debug("Scheduler skipping disabled automation: %s", key)
        return True

    async def _handle_morning_charge(self, now: datetime) -> None:
        """Run morning charge routine at the resolved night buy window start."""
        if self._skip_if_automation_disabled(AUTOMATION_MORNING_CHARGE):
            return
        planned_start = (
            self.coordinator.get_morning_charge_start()
            if self.coordinator is not None
            else None
        )
        if planned_start is None:
            return
        if self.coordinator is None or not await self.coordinator.async_claim_night_buy_window_execution(
            planned_start
        ):
            return
        _LOGGER.info("Scheduler triggering morning grid charge")
        await async_run_morning_charge(
            self.hass,
            entry_id=self.entry.entry_id,
            trigger="scheduler:morning_charge",
        )
        self._publish_schedule_snapshot()

    async def _handle_evening_behavior(self, now: datetime) -> None:
        """Run evening preparation before a possible 22:00 charge start."""
        if self._skip_if_automation_disabled(AUTOMATION_EVENING_BEHAVIOR):
            return
        _LOGGER.info("Scheduler triggering evening behavior")
        await async_run_evening_behavior(
            self.hass,
            entry_id=self.entry.entry_id,
            trigger="scheduler:evening_behavior",
        )
        self._publish_schedule_snapshot()

    async def _handle_afternoon_charge(self, now: datetime) -> None:
        """Run afternoon charge routine at tariff end hour."""
        if self._skip_if_automation_disabled(AUTOMATION_AFTERNOON_CHARGE):
            return
        _LOGGER.info("Scheduler triggering afternoon charge")
        await async_run_afternoon_charge(
            self.hass,
            entry_id=self.entry.entry_id,
            trigger="scheduler:afternoon_charge",
        )
        self._publish_schedule_snapshot()

    async def _handle_program4_solar_reset(self, now: datetime) -> None:
        """Run Program 4 solar-surplus reset at its configured start time."""
        _LOGGER.info("Scheduler triggering Program 4 solar reset")
        await async_run_program4_solar_reset(
            self.hass,
            entry_id=self.entry.entry_id,
            trigger="scheduler:program4_solar_reset",
        )
        self._publish_schedule_snapshot()

    def _evening_second_hour(self) -> int | None:
        """Return the Secondary evening sell hour, if the snapshot has one."""
        secondary = self._windows.evening_sell.secondary
        return None if secondary is None else secondary.hour

    def _primary_evening_window_is_first(self) -> bool:
        """Return whether the primary evening window occurs before the secondary one."""
        primary_hour = self._windows.evening_sell.primary.hour
        secondary_hour = self._evening_second_hour()
        if secondary_hour is None:
            return True
        return primary_hour <= secondary_hour

    async def _handle_evening_sell(self, now: datetime) -> None:
        """Run the primary (`A`) evening sell window."""
        if self._skip_if_automation_disabled(AUTOMATION_EVENING_SELL):
            return
        _LOGGER.info("Scheduler triggering evening primary sell window")
        await async_run_evening_sell(
            self.hass,
            entry_id=self.entry.entry_id,
            is_primary=True,
            is_first=self._primary_evening_window_is_first(),
            trigger="scheduler:evening_sell_primary",
        )
        self._publish_schedule_snapshot()

    async def _handle_morning_sell(self, now: datetime) -> None:
        """Run morning peak sell routine at configured peak hour."""
        if self._skip_if_automation_disabled(AUTOMATION_MORNING_SELL):
            return
        _LOGGER.info("Scheduler triggering morning peak sell")
        await async_run_morning_sell(
            self.hass,
            entry_id=self.entry.entry_id,
            trigger="scheduler:morning_sell",
        )
        self._publish_schedule_snapshot()

    async def _handle_evening_sell_second(self, now: datetime) -> None:
        """Run the secondary (`B`) evening sell window."""
        if self._skip_if_automation_disabled(AUTOMATION_EVENING_SELL):
            return
        _LOGGER.info("Scheduler triggering evening secondary sell window")
        await async_run_evening_sell(
            self.hass,
            entry_id=self.entry.entry_id,
            is_primary=False,
            is_first=not self._primary_evening_window_is_first(),
            trigger="scheduler:evening_sell_secondary",
        )
        self._publish_schedule_snapshot()

    def _reschedule_changed_windows(self, *always: str) -> None:
        """Take a new snapshot and reschedule the actions of the windows that changed.

        The new snapshot is stored first so no `_schedule_*` reads a stale one.
        `always` names reschedule methods that run whether or not a window changed.
        """
        if self._resolver is None:
            return
        new = self._resolver.windows()
        changed = new.changed_from(self._windows)
        self._windows = new
        callbacks = dict.fromkeys(
            (
                *always,
                *(
                    callback
                    for field in sorted(changed)
                    for callback in _WINDOW_RESCHEDULES.get(field, ())
                ),
            )
        )
        for callback in callbacks:
            getattr(self, callback)()

    async def _handle_tariff_start_change(self, event) -> None:
        """Reschedule the actions of the windows a tariff start change moved."""
        if self._completion_restore_pending():
            return
        self._reschedule_changed_windows()

    def _completion_restore_pending(self) -> bool:
        """Return True while completions are restoring; the restore applies deferred changes."""
        return (
            self._charge_completion_restore_task is not None
            and not self._charge_completion_restore_task.done()
        )

    def _handle_coordinator_update(self) -> None:
        """Reschedule Morning Charge, and the actions whose window changed.

        Morning Charge follows the coordinator's claim-aware start, which can
        change without any window changing.
        """
        if self._completion_restore_pending():
            return
        self._reschedule_changed_windows("_schedule_morning_charge")

    async def _handle_night_buy_window_rotation(self, now: datetime) -> None:
        """Rotate persisted night plans at 06:01 even without a source update."""
        if self.coordinator is not None:
            await self.coordinator.async_request_refresh()
        self._schedule_morning_charge()
        self._publish_schedule_snapshot()

    async def _handle_program4_start_time_change(self, event) -> None:
        """Reschedule Program 4 solar reset when its start time changes."""
        self._schedule_program4_solar_reset()

    async def _handle_morning_restore(self, now: datetime) -> None:
        """Restore inverter state after morning sell window."""
        await async_handle_sell_restore(self.hass, self.entry, "morning")
        self._publish_schedule_snapshot()

    async def _handle_evening_restore(self, now: datetime) -> None:
        """Restore inverter state after evening sell window."""
        await async_handle_sell_restore(self.hass, self.entry, "evening")
        self._publish_schedule_snapshot()

    async def _handle_sunrise(self) -> None:
        """Activate hourly daytime price controls after sunrise."""
        _LOGGER.debug("Price-driven actions: sunrise detected — enabling hourly trigger")
        self._start_price_hourly_listener()
        self._publish_schedule_snapshot()

    async def _handle_sunset(self) -> None:
        """Restore normal export operation and deactivate daytime controls."""
        _LOGGER.debug(
            "Price-driven actions: sunset detected — restoring normal operation"
        )
        self._stop_price_hourly_listener()
        decision = await async_restore_export_block_control(
            self.hass,
            entry_id=self.entry.entry_id,
            trigger="scheduler:sunset_export_restore",
        )
        self._store_export_block_decision(decision)
        self._publish_schedule_snapshot()

    async def _handle_price_hourly(self, now: datetime) -> None:
        """Run price-driven controls on the hour during daylight."""
        if not self._is_sun_above_horizon():
            _LOGGER.debug(
                "Price-driven actions: hourly trigger fired outside daylight window — skip"
            )
            return
        await self._handle_price_change(now)

    async def _handle_price_change(self, event_or_now: Any) -> None:
        """Run daytime price-driven controls."""
        if not self._skip_if_automation_disabled(AUTOMATION_SOLAR_CHARGE_BLOCK):
            await async_run_solar_charge_block(
                self.hass,
                entry_id=self.entry.entry_id,
                trigger="scheduler:price_change_solar_charge_block",
            )
        if not self._skip_if_automation_disabled(AUTOMATION_EXPORT_BLOCK_CONTROL):
            await asyncio.sleep(5)
            decision = await async_run_export_block_control(
                self.hass,
                entry_id=self.entry.entry_id,
                trigger="scheduler:price_change_export_block_control",
            )
            self._store_export_block_decision(decision)
        self._publish_schedule_snapshot()

    async def _handle_bev_charging_change(self, event) -> None:
        """Re-evaluate export control immediately when BEV charging changes."""
        if self._skip_if_automation_disabled(AUTOMATION_EXPORT_BLOCK_CONTROL):
            return
        decision = await async_run_export_block_control(
            self.hass,
            entry_id=self.entry.entry_id,
            trigger="state_change:bev_charging",
        )
        self._store_export_block_decision(decision)
        self._publish_schedule_snapshot()

    async def _handle_daily_schedule_refresh(self, now: datetime) -> None:
        """Refresh the published daily schedule snapshot at midnight."""
        self._publish_schedule_snapshot()

    async def _handle_daytime_min_price_restore(self, now: datetime) -> None:
        """Run daytime min price restore decision engine at scheduled time."""
        _LOGGER.info("Scheduler triggering daytime min price restore at %02d:00", now.hour)
        await async_run_daytime_min_price_restore(
            self.hass,
            entry_id=self.entry.entry_id,
            trigger="scheduler:daytime_min_price_restore",
        )

    def _schedule_afternoon_charge(self) -> None:
        """Schedule afternoon charge at the day buy window start hour."""
        if self._afternoon_listener is not None:
            self._afternoon_listener()
            self._afternoon_listener = None

        if self._windows.day_buy.is_fallback:
            _LOGGER.info(
                "Afternoon charge not scheduled: no Day Buy Window is planned for today"
            )
            self._publish_schedule_snapshot()
            return

        hour = self._windows.day_buy.hour
        self._afternoon_listener = async_track_time_change(
            self.hass,
            self._handle_afternoon_charge,
            hour=hour,
            minute=0,
            second=1,
        )
        self._publish_schedule_snapshot()

    def _schedule_program4_solar_reset(self) -> None:
        """Schedule Program 4 solar reset at its configured start time."""
        if self._program4_solar_reset_listener is not None:
            self._program4_solar_reset_listener()
            self._program4_solar_reset_listener = None

        start_time = resolve_prog4_start_time(self.hass, self.entry.data)
        if start_time is None:
            self._publish_schedule_snapshot()
            return

        afternoon_charge_hour = self._windows.day_buy.hour
        if start_time.hour >= afternoon_charge_hour:
            _LOGGER.debug(
                "Program 4 solar reset disabled: start hour %02d is not before afternoon charge hour %02d",
                start_time.hour,
                afternoon_charge_hour,
            )
            self._publish_schedule_snapshot()
            return

        self._program4_solar_reset_listener = async_track_time_change(
            self.hass,
            self._handle_program4_solar_reset,
            hour=start_time.hour,
            minute=start_time.minute,
            second=1,
        )
        self._publish_schedule_snapshot()

    def _schedule_morning_charge(self) -> None:
        """Schedule morning charge at the concrete planned window timestamp."""
        if self._morning_charge_listener is not None:
            self._morning_charge_listener()
            self._morning_charge_listener = None

        start = (
            self.coordinator.get_morning_charge_start()
            if self.coordinator is not None
            else None
        )
        if start is not None:
            now = dt_util.now()
            if start.astimezone(UTC) > now.astimezone(UTC):
                self._morning_charge_listener = async_track_point_in_time(
                    self.hass,
                    self._handle_morning_charge,
                    start,
                )
            else:
                if self.coordinator.missed_morning_charge_is_eligible(now):
                    self._create_task(self._handle_morning_charge(now))
        self._publish_schedule_snapshot()

    def _schedule_evening_sell(self) -> None:
        """Schedule evening peak sell at configured evening max price hour."""
        if self._evening_sell_listener is not None:
            self._evening_sell_listener()
            self._evening_sell_listener = None
        if self._evening_sell_second_listener is not None:
            self._evening_sell_second_listener()
            self._evening_sell_second_listener = None

        hour = self._windows.evening_sell.primary.hour
        self._evening_sell_listener = async_track_time_change(
            self.hass,
            self._handle_evening_sell,
            hour=hour,
            minute=0,
            second=1,
        )

        second_hour = self._evening_second_hour()
        if second_hour is not None:
            self._evening_sell_second_listener = async_track_time_change(
                self.hass,
                self._handle_evening_sell_second,
                hour=second_hour,
                minute=0,
                second=1,
            )
        self._publish_schedule_snapshot()

    def _schedule_morning_sell(self) -> None:
        """Schedule morning peak sell at configured morning max price hour."""
        if self._morning_sell_listener is not None:
            self._morning_sell_listener()
            self._morning_sell_listener = None

        hour = self._windows.morning_sell.primary.hour
        self._morning_sell_listener = async_track_time_change(
            self.hass,
            self._handle_morning_sell,
            hour=hour,
            minute=0,
            second=1,
        )
        self._publish_schedule_snapshot()

    def _schedule_daytime_min_price_restore(self) -> None:
        """Schedule max charge current restore at daytime min price hour."""
        if self._daytime_min_price_listener is not None:
            self._daytime_min_price_listener()
            self._daytime_min_price_listener = None

        daytime_min_price_time = self._windows.consume.start.time()
        hour = daytime_min_price_time.hour
        minute = daytime_min_price_time.minute
        self._daytime_min_price_listener = async_track_time_change(
            self.hass,
            self._handle_daytime_min_price_restore,
            hour=hour,
            minute=minute,
            second=1,
        )
        _LOGGER.debug("Daytime min price restore scheduled for %02d:%02d", hour, minute)
        self._publish_schedule_snapshot()

    def _is_sun_above_horizon(self) -> bool:
        """Return whether the sun entity currently reports daylight."""
        sun_state = self.hass.states.get(SUN_ENTITY)
        return sun_state is not None and sun_state.state == SUN_ABOVE_HORIZON

    def _start_price_hourly_listener(self) -> None:
        """Ensure the hourly daytime price-control listener is active."""
        if self._price_hourly_listener is not None:
            return

        self._price_hourly_listener = async_track_time_change(
            self.hass,
            self._handle_price_hourly,
            hour="*",
            minute=1,
            second=0,
        )

    def _stop_price_hourly_listener(self) -> None:
        """Ensure the hourly daytime price-control listener is inactive."""
        if self._price_hourly_listener is None:
            return

        self._price_hourly_listener()
        self._price_hourly_listener = None

    def _schedule_sell_restores(self) -> None:
        """Schedule dedicated restore listeners one hour after sell start hours."""
        if self._morning_restore_listener is not None:
            self._morning_restore_listener()
            self._morning_restore_listener = None
        if self._evening_restore_listener is not None:
            self._evening_restore_listener()
            self._evening_restore_listener = None

        morning_hour = self._windows.morning_sell.primary.hour
        self._morning_restore_listener = async_track_time_change(
            self.hass,
            self._handle_morning_restore,
            hour=(morning_hour + 1) % 24,
            minute=0,
            second=1,
        )

        evening_hour = self._windows.evening_sell.primary.hour
        second_evening_hour = self._evening_second_hour()
        effective_evening_restore_hour = (
            (max(evening_hour, second_evening_hour) + 1) % 24
            if second_evening_hour is not None
            else (evening_hour + 1) % 24
        )
        self._evening_restore_listener = async_track_time_change(
            self.hass,
            self._handle_evening_restore,
            hour=effective_evening_restore_hour,
            minute=0,
            second=1,
        )
        self._publish_schedule_snapshot()

        self._create_task(
            async_check_pending_sell_restore(self.hass, self.entry)
        )

    def _get_scheduled_actions_sensor(self) -> Any | None:
        """Return the scheduled actions sensor stored for this entry."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id)
        if not isinstance(entry_data, dict):
            return None
        return entry_data.get("scheduled_actions_sensor")

    def _store_export_block_decision(self, decision: dict[str, Any] | None) -> None:
        """Store the latest export control decision for diagnostic publication."""
        if decision is None:
            return
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id)
        if isinstance(entry_data, dict):
            entry_data["last_export_block_control"] = decision

    def _publish_schedule_snapshot(self) -> None:
        """Publish the current daily schedule snapshot to the diagnostic sensor."""
        sensor = self._get_scheduled_actions_sensor()
        if sensor is None:
            return
        sensor.update_schedule(self._build_scheduled_actions_snapshot())

    def _clear_schedule_snapshot(self) -> None:
        """Clear the published daily schedule snapshot."""
        sensor = self._get_scheduled_actions_sensor()
        if sensor is None:
            return
        sensor.clear_schedule()

    def _build_scheduled_actions_snapshot(self) -> dict[str, Any]:
        """Build a structured snapshot of today's scheduled actions."""
        now = dt_util.now()
        timezone_name = str(now.tzinfo)
        windows = self._windows
        actions: list[dict[str, Any]] = []

        actions.append(
            self._build_action_entry(
                key="morning_charge",
                label="Morning grid charge",
                scheduled_for=(
                    self.coordinator.get_morning_charge_start()
                    if self.coordinator is not None
                    else None
                ),
                kind="dynamic",
                source=windows.night_buy.source.value,
                order=10,
            )
        )

        afternoon_charge_hour = self._windows.day_buy.hour
        if not windows.day_buy.is_fallback:
            actions.append(
                self._build_action_entry(
                    key="afternoon_charge",
                    label="Afternoon charge",
                    scheduled_for=self._resolve_local_datetime(
                        hour=afternoon_charge_hour,
                        minute=0,
                        now=now,
                    ),
                    kind="dynamic",
                    source=windows.day_buy.source.value,
                    order=100,
                )
            )

        program4_start_time = resolve_prog4_start_time(self.hass, self.entry.data)
        if (
            program4_start_time is not None
            and program4_start_time.hour < afternoon_charge_hour
        ):
            actions.append(
                self._build_action_entry(
                    key="program4_solar_reset",
                    label="Program 4 solar reset",
                    scheduled_for=self._resolve_local_datetime(
                        hour=program4_start_time.hour,
                        minute=program4_start_time.minute,
                        now=now,
                    ),
                    kind="dynamic",
                    source="prog4_time_start_entity",
                    order=90,
                )
            )

        morning_sell_hour = self._windows.morning_sell.primary.hour
        actions.append(
            self._build_action_entry(
                key="morning_sell",
                label="Morning peak sell",
                scheduled_for=self._resolve_local_datetime(
                    hour=morning_sell_hour,
                    minute=0,
                    now=now,
                ),
                kind="dynamic",
                source=windows.morning_sell.primary.source.value,
                order=110,
            )
        )
        actions.append(
            self._build_action_entry(
                key="morning_sell_restore",
                label="Morning sell restore",
                scheduled_for=self._resolve_local_datetime(
                    hour=(morning_sell_hour + 1) % 24,
                    minute=0,
                    now=now,
                ),
                kind="derived_restore",
                source=windows.morning_sell.primary.source.value,
                order=111,
            )
        )

        evening_sell_hour = self._windows.evening_sell.primary.hour
        actions.append(
            self._build_action_entry(
                key="evening_sell",
                label="Evening peak sell",
                scheduled_for=self._resolve_local_datetime(
                    hour=evening_sell_hour,
                    minute=0,
                    now=now,
                ),
                kind="dynamic",
                source=windows.evening_sell.primary.source.value,
                order=120,
            )
        )

        second_evening_sell_hour = self._evening_second_hour()
        evening_restore_source = windows.evening_sell.primary.source.value
        effective_evening_restore_hour = (evening_sell_hour + 1) % 24
        if second_evening_sell_hour is not None:
            actions.append(
                self._build_action_entry(
                    key="evening_sell_second",
                    label="Evening second-session sell",
                    scheduled_for=self._resolve_local_datetime(
                        hour=second_evening_sell_hour,
                        minute=0,
                        now=now,
                    ),
                    kind="dynamic",
                    source=(
                        windows.evening_sell.secondary or windows.evening_sell.primary
                    ).source.value,
                    order=121,
                )
            )
            if second_evening_sell_hour >= evening_sell_hour:
                effective_evening_restore_hour = (second_evening_sell_hour + 1) % 24
                evening_restore_source = (
                    windows.evening_sell.secondary or windows.evening_sell.primary
                ).source.value

        actions.append(
            self._build_action_entry(
                key="evening_sell_restore",
                label="Evening sell restore",
                scheduled_for=self._resolve_local_datetime(
                    hour=effective_evening_restore_hour,
                    minute=0,
                    now=now,
                ),
                kind="derived_restore",
                source=evening_restore_source,
                order=122,
            )
        )

        daytime_min_price_time = self._windows.consume.start.time()
        actions.append(
            self._build_action_entry(
                key="daytime_min_price_restore",
                label="Daytime min price restore",
                scheduled_for=self._resolve_local_datetime(
                    hour=daytime_min_price_time.hour,
                    minute=daytime_min_price_time.minute,
                    now=now,
                ),
                kind="dynamic",
                source=windows.consume.source.value,
                order=130,
            )
        )

        actions.append(
            self._build_action_entry(
                key="evening_behavior",
                label="Evening behavior",
                scheduled_for=self._resolve_local_datetime(
                    hour=EVENING_BEHAVIOR_PREPARE_HOUR,
                    minute=EVENING_BEHAVIOR_PREPARE_MINUTE,
                    now=now,
                ),
                kind="fixed",
                source="fixed",
                order=140,
            )
        )

        has_solar_price_context = bool(self.entry.data.get(CONF_SELL_PRICE_SENSOR))
        has_sell_context = bool(
            self.entry.data.get(CONF_SELL_PRICE_SENSOR) or self.entry.data.get(CONF_PRICE_SENSOR)
        )

        if has_solar_price_context:
            actions.append(
                self._build_action_entry(
                    key="solar_charge_block",
                    label="Solar charge block check",
                    scheduled_for=None,
                    kind="event_driven",
                    source="sell_price_sensor",
                    order=999,
                    trigger="hourly_between_sunrise_and_sunset",
                )
            )
        if has_sell_context:
            actions.append(
                self._build_action_entry(
                    key="export_block_control",
                    label="Export block control",
                    scheduled_for=None,
                    kind="event_driven",
                    source="sell_price_sensor",
                    order=1000,
                    trigger="hourly_between_sunrise_and_sunset",
                )
            )

        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        completion_plans = (
            entry_data.get("charge_completion_plans", {})
            if isinstance(entry_data, dict)
            else {}
        )
        if isinstance(completion_plans, dict):
            for charge_type, plan in completion_plans.items():
                if not isinstance(plan, dict):
                    continue
                scheduled_for = dt_util.parse_datetime(str(plan.get("complete_at")))
                if scheduled_for is None:
                    continue
                actions.append(
                    self._build_action_entry(
                        key=f"{charge_type}_charge_completion",
                        label=f"{str(charge_type).title()} charge completion",
                        scheduled_for=dt_util.as_local(scheduled_for),
                        kind="dynamic",
                        source=str(
                            plan.get("window_source")
                            or f"{charge_type}_buy_window_end"
                        ),
                        order=105 if charge_type == "morning" else 106,
                    )
                )

        actions.sort(
            key=lambda item: (
                item["time"] is None,
                item["time"] or "",
                item["order"],
                item["key"],
            )
        )
        next_action = next(
            (
                action
                for action in actions
                if action["time"] is not None and action["time"] >= now.isoformat()
            ),
            None,
        )

        summary = {
            "count": len(actions),
            "fixed_count": sum(1 for action in actions if action["kind"] in {"fixed", "fixed_recurring"}),
            "dynamic_count": sum(1 for action in actions if action["kind"] in {"dynamic", "derived_restore"}),
            "event_driven_count": sum(1 for action in actions if action["kind"] == "event_driven"),
        }

        return {
            "date": now.date().isoformat(),
            "timezone": timezone_name,
            "generated_at": now.isoformat(),
            "next_action": None if next_action is None else {
                "key": next_action["key"],
                "label": next_action["label"],
                "time": next_action["time"],
            },
            "actions": actions,
            "summary": summary,
            "last_export_block_control": (
                entry_data.get("last_export_block_control")
                if isinstance(entry_data, dict)
                else None
            ),
        }

    def _build_action_entry(
        self,
        *,
        key: str,
        label: str,
        scheduled_for: datetime | None,
        kind: str,
        source: str,
        order: int,
        trigger: str | None = None,
    ) -> dict[str, Any]:
        """Build a serializable action entry."""
        entry: dict[str, Any] = {
            "key": key,
            "label": label,
            "time": scheduled_for.isoformat() if scheduled_for is not None else None,
            "time_local": (
                scheduled_for.strftime("%H:%M") if scheduled_for is not None else None
            ),
            "kind": kind,
            "source": source,
            "enabled": self._automation_enabled(key),
            "order": order,
        }
        if not entry["enabled"]:
            entry["status"] = "disabled"
        if trigger is not None:
            entry["trigger"] = trigger
        return entry

    def _resolve_local_datetime(
        self,
        *,
        hour: int,
        minute: int,
        now: datetime,
    ) -> datetime:
        """Resolve a local datetime for today's snapshot."""
        scheduled_for = now.replace(
            hour=hour % 24,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if hour >= 24:
            scheduled_for += timedelta(days=1)
        return scheduled_for
