"""Persistent completion handling for temporary charge targets."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any, Literal

from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_BATTERY_SOC_SENSOR,
    CONF_MIN_SOC,
    CONF_MIN_SOC_PV,
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG4_SOC_ENTITY,
    DOMAIN,
    STORAGE_KEY_CHARGE_COMPLETION,
    STORAGE_VERSION_CHARGE_COMPLETION,
)
from ..controllers.inverter import set_program_soc
from ..helpers import get_float_state_info, get_internal_sensor_entity_id
from ..utils.decision_dump import active_decision_audit
from ..utils.logging import DecisionOutcome, log_decision_unified

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

ChargeType = Literal["morning", "afternoon"]
_LOGGER = logging.getLogger(__name__)
_RUNTIME_KEY = "charge_completion_listeners"
_PLANS_KEY = "charge_completion_plans"
_SNAPSHOT_CALLBACK_KEY = "charge_completion_snapshot_callback"


def resolve_charge_window(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    charge_type: ChargeType,
    fallback_start_hour: int,
    fallback_end_hour: int,
) -> tuple[datetime, datetime]:
    """Resolve a buy window to concrete local datetimes."""
    now = dt_util.now()
    suffix = "night_buy_window" if charge_type == "morning" else "day_buy_window"
    entity_id = get_internal_sensor_entity_id(
        hass,
        entry_id=entry.entry_id,
        unique_id_suffix=suffix,
    )
    state = hass.states.get(entity_id) if entity_id else None
    attributes = getattr(state, "attributes", {}) if state is not None else {}
    if isinstance(attributes, dict):
        start = dt_util.parse_datetime(str(attributes.get("start_time")))
        end = dt_util.parse_datetime(str(attributes.get("end_time")))
        if start is not None and end is not None:
            return dt_util.as_local(start), dt_util.as_local(end)
        state_time = dt_util.parse_time(str(getattr(state, "state", "")))
        try:
            duration_hours = float(attributes.get("duration_hours"))
        except (TypeError, ValueError):
            duration_hours = 0.0
        if state_time is not None and duration_hours > 0:
            start = now.replace(
                hour=state_time.hour,
                minute=state_time.minute,
                second=0,
                microsecond=0,
            )
            end = start + timedelta(hours=duration_hours)
            if end <= now:
                start += timedelta(days=1)
                end += timedelta(days=1)
            return start, end

    start = now.replace(
        hour=fallback_start_hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    end = now.replace(
        hour=fallback_end_hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    if fallback_end_hour <= fallback_start_hour:
        end += timedelta(days=1)
    if end <= now:
        start += timedelta(days=1)
        end += timedelta(days=1)
    return start, end


def _store(hass: HomeAssistant, entry: ConfigEntry, charge_type: ChargeType) -> Store:
    """Return the versioned store for one charge completion."""
    return Store(
        hass,
        STORAGE_VERSION_CHARGE_COMPLETION,
        f"{STORAGE_KEY_CHARGE_COMPLETION}.{entry.entry_id}.{charge_type}",
    )


def _listeners(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return the runtime listener registry."""
    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    return entry_data.setdefault(_RUNTIME_KEY, {})


def _plans(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return the runtime completion-plan registry."""
    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    return entry_data.setdefault(_PLANS_KEY, {})


def _publish_schedule_snapshot(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Refresh the schedule snapshot after a completion plan changes."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    callback = entry_data.get(_SNAPSHOT_CALLBACK_KEY)
    if callable(callback):
        callback()


def _cancel_listener(hass: HomeAssistant, entry: ConfigEntry, charge_type: str) -> None:
    """Cancel a pending runtime listener."""
    remove_listener = _listeners(hass, entry).pop(charge_type, None)
    if remove_listener is not None:
        remove_listener()


async def async_schedule_charge_completion(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    charge_type: ChargeType,
    complete_at: datetime,
    window_start: datetime,
    window_end: datetime,
) -> None:
    """Persist and schedule a temporary charge-target completion."""
    plan = {
        "charge_type": charge_type,
        "complete_at": complete_at.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    }
    await _store(hass, entry, charge_type).async_save(plan)
    _plans(hass, entry)[charge_type] = plan
    _cancel_listener(hass, entry, charge_type)
    _publish_schedule_snapshot(hass, entry)

    async def _complete(_now: datetime) -> None:
        await async_handle_charge_completion(hass, entry, charge_type)

    _listeners(hass, entry)[charge_type] = async_track_point_in_time(
        hass,
        _complete,
        complete_at,
    )


async def async_handle_charge_completion(
    hass: HomeAssistant,
    entry: ConfigEntry,
    charge_type: ChargeType,
) -> None:
    """Complete one temporary charge target and clear its persisted plan."""
    store = _store(hass, entry, charge_type)
    plan = await store.async_load()
    if not isinstance(plan, dict):
        return

    _cancel_listener(hass, entry, charge_type)
    context = Context()
    config = entry.data
    scenario = (
        "Morning Charge Completion"
        if charge_type == "morning"
        else "Afternoon Charge Completion"
    )
    prog_entity = config.get(
        CONF_PROG2_SOC_ENTITY if charge_type == "morning" else CONF_PROG4_SOC_ENTITY
    )
    current_prog_soc, _, prog_error = get_float_state_info(
        hass, str(prog_entity) if prog_entity else None
    )

    target_soc: float | None = None
    failure_reason: str | None = None
    retry_after_state_failure = False
    retry_after_write_failure = False
    if prog_error is not None or current_prog_soc is None:
        failure_reason = "Program SOC unavailable or invalid at completion"
        retry_after_state_failure = True
    elif charge_type == "morning":
        target_soc = float(config.get(CONF_MIN_SOC, 15))
    else:
        battery_soc, _, battery_error = get_float_state_info(
            hass,
            str(config.get(CONF_BATTERY_SOC_SENSOR))
            if config.get(CONF_BATTERY_SOC_SENSOR)
            else None,
        )
        if battery_error is not None or battery_soc is None:
            failure_reason = "Battery SOC unavailable or invalid at completion"
        else:
            target_soc = min(
                battery_soc,
                float(config.get(CONF_MIN_SOC_PV, 15)),
            )

    details = {
        "program_soc": target_soc,
        "window_start": plan.get("window_start"),
        "window_end": plan.get("window_end"),
    }
    async with active_decision_audit(
        hass,
        entry,
        trigger=f"scheduler:{charge_type}_charge_completion",
    ):
        if failure_reason is not None:
            outcome = DecisionOutcome(
                scenario=scenario,
                action_type="charge_completion_failed",
                summary=f"{scenario} failed",
                reason=failure_reason,
                details=details,
            )
        elif abs(float(target_soc) - current_prog_soc) <= 0.01:
            outcome = DecisionOutcome(
                scenario=scenario,
                action_type="no_action",
                summary=f"Program SOC already {target_soc:.0f}%",
                reason="Completion target already present",
                details=details,
            )
        else:
            try:
                await set_program_soc(
                    hass,
                    str(prog_entity),
                    float(target_soc),
                    entry=entry,
                    logger=_LOGGER,
                    context=context,
                )
            except HomeAssistantError as err:
                retry_after_write_failure = True
                outcome = DecisionOutcome(
                    scenario=scenario,
                    action_type="charge_completion_failed",
                    summary=f"{scenario} failed",
                    reason=str(err),
                    details=details,
                )
            else:
                outcome = DecisionOutcome(
                    scenario=scenario,
                    action_type="charge_completed",
                    summary=f"Set Program SOC to {target_soc:.0f}%",
                    details=details,
                    entities_changed=[
                        {"entity_id": str(prog_entity), "value": float(target_soc)}
                    ],
                )

        await log_decision_unified(
            hass,
            entry,
            outcome,
            context=context,
            logger=_LOGGER,
        )
        if retry_after_write_failure or retry_after_state_failure:
            window_start = dt_util.parse_datetime(str(plan["window_start"]))
            window_end = dt_util.parse_datetime(str(plan["window_end"]))
            if window_start is None or window_end is None:
                _LOGGER.error(
                    "Cannot retry %s charge completion with invalid window data",
                    charge_type,
                )
                await store.async_remove()
                _plans(hass, entry).pop(charge_type, None)
                _publish_schedule_snapshot(hass, entry)
                return
            await async_schedule_charge_completion(
                hass,
                entry,
                charge_type=charge_type,
                complete_at=dt_util.now() + timedelta(minutes=5),
                window_start=dt_util.as_local(window_start),
                window_end=dt_util.as_local(window_end),
            )
            return

        await store.async_remove()
        _plans(hass, entry).pop(charge_type, None)
        _publish_schedule_snapshot(hass, entry)


async def async_restore_charge_completions(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Restore pending completion listeners and run overdue plans."""
    now = dt_util.now()
    for charge_type in ("morning", "afternoon"):
        store = _store(hass, entry, charge_type)
        plan = await store.async_load()
        if not isinstance(plan, dict):
            continue
        complete_at = dt_util.parse_datetime(str(plan.get("complete_at")))
        window_start = dt_util.parse_datetime(str(plan.get("window_start")))
        window_end = dt_util.parse_datetime(str(plan.get("window_end")))
        if complete_at is None or window_start is None or window_end is None:
            _LOGGER.error("Invalid persisted %s charge completion plan", charge_type)
            await store.async_remove()
            _plans(hass, entry).pop(charge_type, None)
            _publish_schedule_snapshot(hass, entry)
            continue
        complete_at = dt_util.as_local(complete_at)
        window_start = dt_util.as_local(window_start)
        window_end = dt_util.as_local(window_end)
        if complete_at <= now:
            _plans(hass, entry)[charge_type] = plan
            await async_handle_charge_completion(hass, entry, charge_type)
        else:
            await async_schedule_charge_completion(
                hass,
                entry,
                charge_type=charge_type,
                complete_at=complete_at,
                window_start=window_start,
                window_end=window_end,
            )


def cancel_charge_completion_listeners(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Cancel runtime completion listeners without removing persisted plans."""
    listeners = _listeners(hass, entry)
    for remove_listener in list(listeners.values()):
        remove_listener()
    listeners.clear()
