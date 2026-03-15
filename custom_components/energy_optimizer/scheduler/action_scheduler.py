"""Action scheduler for Energy Optimizer."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from time import sleep
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.core import Context
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR,
    CONF_EVENING_MAX_PRICE_HOUR_SENSOR,
    CONF_EVENING_SECOND_MAX_PRICE_HOUR_SENSOR,
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_MORNING_MAX_PRICE_HOUR_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_TARIFF_END_HOUR_SENSOR,
    DEFAULT_MAX_CHARGE_CURRENT,
    DOMAIN,
)
from ..controllers.inverter import set_max_charge_current
from ..decision_engine.evening_sell import async_run_evening_sell
from ..decision_engine.morning_sell import async_run_morning_sell
from ..decision_engine.evening_behavior import async_run_evening_behavior
from ..decision_engine.afternoon_charge import async_run_afternoon_charge
from ..decision_engine.morning_charge import async_run_morning_charge
from ..decision_engine.solar_charge_block import async_run_solar_charge_block
from ..decision_engine.export_block_control import async_run_export_block_control
from ..service_handlers.sell_restore import (
    async_check_pending_sell_restore,
    async_handle_sell_restore,
)
from ..helpers import (
    get_float_state_info,
    resolve_daytime_min_price_time,
    resolve_evening_max_price_hour,
    resolve_evening_second_max_price_hour,
    resolve_morning_max_price_hour,
    resolve_tariff_end_hour,
)

if TYPE_CHECKING:
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
        self._evening_sell_second_listener: Callable[[], None] | None = None
        self._morning_restore_listener: Callable[[], None] | None = None
        self._evening_restore_listener: Callable[[], None] | None = None
        self._daytime_min_price_listener: Callable[[], None] | None = None

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
        self._listeners.append(
            async_track_time_change(
                self.hass,
                self._handle_daily_schedule_refresh,
                hour=0,
                minute=0,
                second=0,
            )
        )
        self._schedule_morning_sell()
        self._schedule_evening_sell()
        self._schedule_sell_restores()
        self._schedule_daytime_min_price_restore()

        price_sensor = self.entry.data.get(CONF_PRICE_SENSOR)
        if price_sensor:
            self._listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [str(price_sensor)],
                    self._handle_price_change,
                )
            )
        else:
            _LOGGER.warning(
                "Price-driven actions: price sensor not configured — export and solar charge block controls disabled"
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

        evening_peak_hour_entity = self.entry.data.get(CONF_EVENING_MAX_PRICE_HOUR_SENSOR)
        if evening_peak_hour_entity:
            self._listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [str(evening_peak_hour_entity)],
                    self._handle_evening_peak_hour_change,
                )
            )

        evening_second_peak_hour_entity = self.entry.data.get(
            CONF_EVENING_SECOND_MAX_PRICE_HOUR_SENSOR
        )
        if evening_second_peak_hour_entity:
            self._listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [str(evening_second_peak_hour_entity)],
                    self._handle_evening_second_peak_hour_change,
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

        daytime_min_price_hour_entity = self.entry.data.get(CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR)
        if daytime_min_price_hour_entity:
            self._listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [str(daytime_min_price_hour_entity)],
                    self._handle_daytime_min_price_hour_change,
                )
            )

        self._publish_schedule_snapshot()
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
        self._clear_schedule_snapshot()

    async def _handle_morning_charge(self, now: datetime) -> None:
        """Run morning charge routine at 04:00."""
        _LOGGER.info("Scheduler triggering morning grid charge")
        await async_run_morning_charge(
            self.hass,
            entry_id=self.entry.entry_id,
        )
        self._publish_schedule_snapshot()

    async def _handle_evening_behavior(self, now: datetime) -> None:
        """Run evening behavior routine at 22:00."""
        _LOGGER.info("Scheduler triggering evening behavior")
        await async_run_evening_behavior(
            self.hass,
            entry_id=self.entry.entry_id,
        )
        self._publish_schedule_snapshot()

    async def _handle_afternoon_charge(self, now: datetime) -> None:
        """Run afternoon charge routine at tariff end hour."""
        _LOGGER.info("Scheduler triggering afternoon charge")
        await async_run_afternoon_charge(
            self.hass,
            entry_id=self.entry.entry_id,
        )
        self._publish_schedule_snapshot()

    def _primary_evening_window_is_first(self) -> bool:
        """Return whether the primary evening window occurs before the secondary one."""
        primary_hour = resolve_evening_max_price_hour(self.hass, self.entry.data, default_hour=17)
        secondary_hour = resolve_evening_second_max_price_hour(self.hass, self.entry.data)
        if secondary_hour is None:
            return True
        return primary_hour <= secondary_hour

    async def _handle_evening_sell(self, now: datetime) -> None:
        """Run the primary (`A`) evening sell window."""
        _LOGGER.info("Scheduler triggering evening primary sell window")
        await async_run_evening_sell(
            self.hass,
            entry_id=self.entry.entry_id,
            is_primary=True,
            is_first=self._primary_evening_window_is_first(),
        )
        self._publish_schedule_snapshot()

    async def _handle_morning_sell(self, now: datetime) -> None:
        """Run morning peak sell routine at configured peak hour."""
        _LOGGER.info("Scheduler triggering morning peak sell")
        await async_run_morning_sell(
            self.hass,
            entry_id=self.entry.entry_id,
        )
        self._publish_schedule_snapshot()

    async def _handle_evening_sell_second(self, now: datetime) -> None:
        """Run the secondary (`B`) evening sell window."""
        _LOGGER.info("Scheduler triggering evening secondary sell window")
        await async_run_evening_sell(
            self.hass,
            entry_id=self.entry.entry_id,
            is_primary=False,
            is_first=not self._primary_evening_window_is_first(),
        )
        self._publish_schedule_snapshot()

    async def _handle_tariff_end_change(self, event) -> None:
        """Reschedule afternoon charge when tariff end hour changes."""
        self._schedule_afternoon_charge()

    async def _handle_evening_peak_hour_change(self, event) -> None:
        """Reschedule evening peak sell when peak hour changes."""
        self._schedule_evening_sell()
        self._schedule_sell_restores()

    async def _handle_evening_second_peak_hour_change(self, event) -> None:
        """Reschedule evening sell when second-best price hour changes."""
        self._schedule_evening_sell()
        self._schedule_sell_restores()

    async def _handle_morning_peak_hour_change(self, event) -> None:
        """Reschedule morning peak sell when peak hour changes."""
        self._schedule_morning_sell()
        self._schedule_sell_restores()

    async def _handle_morning_restore(self, now: datetime) -> None:
        """Restore inverter state after morning sell window."""
        await async_handle_sell_restore(self.hass, self.entry, "morning")
        self._publish_schedule_snapshot()

    async def _handle_evening_restore(self, now: datetime) -> None:
        """Restore inverter state after evening sell window."""
        await async_handle_sell_restore(self.hass, self.entry, "evening")
        self._publish_schedule_snapshot()

    async def _handle_price_change(self, event) -> None:
        """Run price-driven controls when price sensor value changes."""
        await async_run_solar_charge_block(
            self.hass,
            entry_id=self.entry.entry_id,
        )
        sleep(5)
        await async_run_export_block_control(
            self.hass,
            entry_id=self.entry.entry_id,
        )
        self._publish_schedule_snapshot()

    async def _handle_daily_schedule_refresh(self, now: datetime) -> None:
        """Refresh the published daily schedule snapshot at midnight."""
        self._publish_schedule_snapshot()

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
        self._publish_schedule_snapshot()

    def _schedule_evening_sell(self) -> None:
        """Schedule evening peak sell at configured evening max price hour."""
        if self._evening_sell_listener is not None:
            self._evening_sell_listener()
            self._evening_sell_listener = None
        if self._evening_sell_second_listener is not None:
            self._evening_sell_second_listener()
            self._evening_sell_second_listener = None

        hour = resolve_evening_max_price_hour(self.hass, self.entry.data, default_hour=17)
        self._evening_sell_listener = async_track_time_change(
            self.hass,
            self._handle_evening_sell,
            hour=hour,
            minute=0,
            second=0,
        )

        second_hour = resolve_evening_second_max_price_hour(self.hass, self.entry.data)
        if second_hour is not None:
            self._evening_sell_second_listener = async_track_time_change(
                self.hass,
                self._handle_evening_sell_second,
                hour=second_hour,
                minute=0,
                second=0,
            )
        self._publish_schedule_snapshot()

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
        self._publish_schedule_snapshot()

    async def _handle_daytime_min_price_restore(self, now: datetime) -> None:
        """Restore max charge current to configured default at daytime min price hour."""
        _LOGGER.info("Scheduler triggering daytime min price restore at %02d:00", now.hour)
        config = self.entry.data
        max_charge_entity = config.get(CONF_MAX_CHARGE_CURRENT_ENTITY)
        max_charge_value, _raw, error = get_float_state_info(self.hass, max_charge_entity)
        if error is not None:
            _LOGGER.warning(
                "Daytime min price restore: cannot read max charge current (%s) — skip", error
            )
            return
        if max_charge_value is None:
            _LOGGER.warning("Daytime min price restore: max charge current has no value — skip")
            return
        if max_charge_value >= DEFAULT_MAX_CHARGE_CURRENT:
            _LOGGER.debug(
                "Daytime min price restore: max charge current already %.0f — skip", max_charge_value
            )
            return
        _LOGGER.info(
            "Daytime min price restore: setting max charge current to %.0f (was %.0f)",
            float(DEFAULT_MAX_CHARGE_CURRENT),
            max_charge_value,
        )
        await set_max_charge_current(
            self.hass,
            max_charge_entity,
            DEFAULT_MAX_CHARGE_CURRENT,
            entry=self.entry,
            logger=_LOGGER,
            context=Context(),
        )
        self._publish_schedule_snapshot()

    async def _handle_daytime_min_price_hour_change(self, event) -> None:
        """Reschedule daytime min price restore when the hour sensor changes."""
        self._schedule_daytime_min_price_restore()

    def _schedule_daytime_min_price_restore(self) -> None:
        """Schedule max charge current restore at daytime min price hour."""
        if self._daytime_min_price_listener is not None:
            self._daytime_min_price_listener()
            self._daytime_min_price_listener = None

        if not self.entry.data.get(CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR):
            _LOGGER.debug("Daytime min price restore: hour sensor not configured — skipping schedule")
            self._publish_schedule_snapshot()
            return

        daytime_min_price_time = resolve_daytime_min_price_time(self.hass, self.entry.data)
        hour = daytime_min_price_time.hour
        minute = daytime_min_price_time.minute
        self._daytime_min_price_listener = async_track_time_change(
            self.hass,
            self._handle_daytime_min_price_restore,
            hour=hour,
            minute=minute,
            second=0,
        )
        _LOGGER.debug("Daytime min price restore scheduled for %02d:%02d", hour, minute)
        self._publish_schedule_snapshot()

    def _schedule_sell_restores(self) -> None:
        """Schedule dedicated restore listeners one hour after sell start hours."""
        if self._morning_restore_listener is not None:
            self._morning_restore_listener()
            self._morning_restore_listener = None
        if self._evening_restore_listener is not None:
            self._evening_restore_listener()
            self._evening_restore_listener = None

        morning_hour = resolve_morning_max_price_hour(self.hass, self.entry.data, default_hour=7)
        self._morning_restore_listener = async_track_time_change(
            self.hass,
            self._handle_morning_restore,
            hour=(morning_hour + 1) % 24,
            minute=0,
            second=0,
        )

        evening_hour = resolve_evening_max_price_hour(self.hass, self.entry.data, default_hour=17)
        second_evening_hour = resolve_evening_second_max_price_hour(self.hass, self.entry.data)
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
            second=0,
        )
        self._publish_schedule_snapshot()

        self.hass.async_create_task(
            async_check_pending_sell_restore(self.hass, self.entry)
        )

    def _get_scheduled_actions_sensor(self) -> Any | None:
        """Return the scheduled actions sensor stored for this entry."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id)
        if not isinstance(entry_data, dict):
            return None
        return entry_data.get("scheduled_actions_sensor")

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
        actions: list[dict[str, Any]] = []

        actions.append(
            self._build_action_entry(
                key="morning_charge",
                label="Morning grid charge",
                scheduled_for=self._resolve_local_datetime(hour=4, minute=0, now=now),
                kind="fixed",
                source="fixed",
                order=10,
            )
        )

        tariff_end_hour = resolve_tariff_end_hour(self.hass, self.entry.data)
        actions.append(
            self._build_action_entry(
                key="afternoon_charge",
                label="Afternoon charge",
                scheduled_for=self._resolve_local_datetime(
                    hour=tariff_end_hour,
                    minute=0,
                    now=now,
                ),
                kind="dynamic",
                source="tariff_end_hour_sensor",
                order=100,
            )
        )

        morning_sell_hour = resolve_morning_max_price_hour(
            self.hass,
            self.entry.data,
            default_hour=7,
        )
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
                source="morning_max_price_hour_sensor",
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
                source="morning_max_price_hour_sensor_plus_1h",
                order=111,
            )
        )

        evening_sell_hour = resolve_evening_max_price_hour(
            self.hass,
            self.entry.data,
            default_hour=17,
        )
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
                source="evening_max_price_hour_sensor",
                order=120,
            )
        )

        second_evening_sell_hour = resolve_evening_second_max_price_hour(
            self.hass,
            self.entry.data,
        )
        evening_restore_source = "evening_max_price_hour_sensor_plus_1h"
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
                    source="evening_second_max_price_hour_sensor",
                    order=121,
                )
            )
            if second_evening_sell_hour >= evening_sell_hour:
                effective_evening_restore_hour = (second_evening_sell_hour + 1) % 24
                evening_restore_source = "evening_second_max_price_hour_sensor_plus_1h"

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

        if self.entry.data.get(CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR):
            daytime_min_price_time = resolve_daytime_min_price_time(self.hass, self.entry.data)
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
                    source="daytime_min_price_hour_sensor",
                    order=130,
                )
            )

        actions.append(
            self._build_action_entry(
                key="evening_behavior",
                label="Evening behavior",
                scheduled_for=self._resolve_local_datetime(hour=22, minute=0, now=now),
                kind="fixed",
                source="fixed",
                order=140,
            )
        )

        if self.entry.data.get(CONF_PRICE_SENSOR):
            actions.append(
                self._build_action_entry(
                    key="solar_charge_block",
                    label="Solar charge block check",
                    scheduled_for=None,
                    kind="event_driven",
                    source="price_sensor",
                    order=999,
                    trigger="price_sensor_state_change",
                )
            )
            actions.append(
                self._build_action_entry(
                    key="export_block_control",
                    label="Export block control",
                    scheduled_for=None,
                    kind="event_driven",
                    source="price_sensor",
                    order=1000,
                    trigger="price_sensor_state_change",
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
            "enabled": True,
            "order": order,
        }
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
