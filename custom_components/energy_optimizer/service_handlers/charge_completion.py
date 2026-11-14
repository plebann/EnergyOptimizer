"""Persistent completion handling for temporary charge targets."""
from __future__ import annotations

import asyncio
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
    CONF_GRID_CHARGE_CURRENT_ENTITY,
    CONF_MIN_SOC,
    CONF_MIN_SOC_PV,
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG4_SOC_ENTITY,
    DOMAIN,
    STORAGE_KEY_CHARGE_COMPLETION,
    STORAGE_VERSION_CHARGE_COMPLETION,
)
from ..controllers.inverter import set_charge_current, set_program_soc
from ..helpers import get_float_state_info
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
_MORNING_LOCK_KEY = "morning_charge_lock"


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


def morning_charge_lock(hass: HomeAssistant, entry: ConfigEntry) -> asyncio.Lock:
    """Return the per-entry lock serializing Morning Charge and its completion.

    Morning Charge reads program SOCs, writes targets and records the completion
    plan; completion reads that plan and restores. Holding one lock across each
    keeps overlapping manual and scheduled runs from losing the original SOC.
    """
    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    lock = entry_data.get(_MORNING_LOCK_KEY)
    if lock is None:
        lock = entry_data[_MORNING_LOCK_KEY] = asyncio.Lock()
    return lock


def get_charge_completion_plan(
    hass: HomeAssistant, entry: ConfigEntry, charge_type: ChargeType
) -> dict[str, Any] | None:
    """Return the pending completion plan for one charge type, if any."""
    plan = _plans(hass, entry).get(charge_type)
    return plan if isinstance(plan, dict) else None


async def async_load_charge_completion_plan(
    hass: HomeAssistant, entry: ConfigEntry, charge_type: ChargeType
) -> dict[str, Any] | None:
    """Return the pending plan, reading the store when recovery has not run yet."""
    plan = get_charge_completion_plan(hass, entry, charge_type)
    if plan is not None:
        return plan
    stored = await _store(hass, entry, charge_type).async_load()
    return stored if isinstance(stored, dict) else None


def plan_restore_targets(plan: dict[str, Any]) -> dict[str, float]:
    """Return the entity -> Normal SOC Target map recorded in a plan."""
    programs = plan.get("programs")
    if not isinstance(programs, list):
        return {}
    return {
        str(program["entity_id"]): float(program["soc"])
        for program in programs
        if isinstance(program, dict)
    }


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


async def async_clear_charge_completion(
    hass: HomeAssistant, entry: ConfigEntry, charge_type: ChargeType
) -> None:
    """Drop a pending completion plan and its listener."""
    _cancel_listener(hass, entry, charge_type)
    await _store(hass, entry, charge_type).async_remove()
    _plans(hass, entry).pop(charge_type, None)
    _publish_schedule_snapshot(hass, entry)


async def async_schedule_charge_completion(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    charge_type: ChargeType,
    complete_at: datetime,
    window_start: datetime,
    window_end: datetime,
    window_source: str | None = None,
    restore_targets: dict[str, float] | None = None,
) -> None:
    """Persist and schedule a temporary charge-target completion.

    ``restore_targets`` maps each program SOC entity to the Normal SOC Target it
    returns to at completion; a plan without it uses the legacy single-program
    completion.
    """
    plan: dict[str, Any] = {
        "charge_type": charge_type,
        "complete_at": complete_at.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    }
    if window_source is not None:
        plan["window_source"] = window_source
    if restore_targets is not None:
        plan["programs"] = [
            {"entity_id": entity_id, "soc": soc}
            for entity_id, soc in restore_targets.items()
        ]
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
    if charge_type == "morning":
        async with morning_charge_lock(hass, entry):
            await _async_handle_charge_completion(hass, entry, charge_type)
        return
    await _async_handle_charge_completion(hass, entry, charge_type)


async def _async_handle_charge_completion(
    hass: HomeAssistant,
    entry: ConfigEntry,
    charge_type: ChargeType,
) -> None:
    """Complete one temporary charge target without taking the Morning lock."""
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
    restore_targets = plan_restore_targets(plan) if charge_type == "morning" else {}
    if restore_targets:
        await _async_complete_program_set(
            hass, entry, store, plan, restore_targets, context, scenario
        )
        return
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
            grid_charge_current_entity = config.get(CONF_GRID_CHARGE_CURRENT_ENTITY)
            entities_changed: list[dict[str, object]] = []
            if grid_charge_current_entity:
                try:
                    await set_charge_current(
                        hass,
                        str(grid_charge_current_entity),
                        0.0,
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
                    entities_changed.append(
                        {"entity_id": str(grid_charge_current_entity), "value": 0.0}
                    )
            if not retry_after_write_failure:
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
                    entities_changed.append(
                        {"entity_id": str(prog_entity), "value": float(target_soc)}
                    )
                    outcome = DecisionOutcome(
                        scenario=scenario,
                        action_type="charge_completed",
                        summary=f"Set Program SOC to {target_soc:.0f}%",
                        details=details,
                        entities_changed=entities_changed,
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
                window_source=plan.get("window_source"),
            )
            return

        await store.async_remove()
        _plans(hass, entry).pop(charge_type, None)
        _publish_schedule_snapshot(hass, entry)


def _read_completion_state(
    hass: HomeAssistant, restore_targets: dict[str, float]
) -> tuple[dict[str, float], dict[str, float], list[str]]:
    """Split programs into those to restore, unreadable ones and failure reasons."""
    pending: dict[str, float] = {}
    failures: dict[str, float] = {}
    reasons: list[str] = []
    for entity_id, normal_soc in restore_targets.items():
        current, _, error = get_float_state_info(hass, entity_id)
        if error is not None or current is None:
            failures[entity_id] = normal_soc
            reasons.append(f"{entity_id}: Program SOC unavailable or invalid at completion")
        elif abs(normal_soc - current) > 0.01:
            pending[entity_id] = normal_soc
    return pending, failures, reasons


async def _restore_programs(
    hass: HomeAssistant,
    entry: ConfigEntry,
    context: Context,
    pending: dict[str, float],
    failures: dict[str, float],
    reasons: list[str],
) -> list[dict[str, object]]:
    """Zero the grid charge current once, then restore each program on its own."""
    entities_changed: list[dict[str, object]] = []
    grid_charge_current_entity = entry.data.get(CONF_GRID_CHARGE_CURRENT_ENTITY)
    if pending and grid_charge_current_entity:
        try:
            await set_charge_current(
                hass,
                str(grid_charge_current_entity),
                0.0,
                entry=entry,
                logger=_LOGGER,
                context=context,
            )
        except HomeAssistantError as err:
            failures.update(pending)
            reasons.append(str(err))
            return entities_changed
        entities_changed.append(
            {"entity_id": str(grid_charge_current_entity), "value": 0.0}
        )
    for entity_id, normal_soc in pending.items():
        try:
            await set_program_soc(
                hass,
                entity_id,
                normal_soc,
                entry=entry,
                logger=_LOGGER,
                context=context,
            )
        except HomeAssistantError as err:
            failures[entity_id] = normal_soc
            reasons.append(f"{entity_id}: {err}")
        else:
            entities_changed.append({"entity_id": entity_id, "value": normal_soc})
    return entities_changed


def _program_set_outcome(
    scenario: str,
    details: dict[str, object],
    failed: bool,
    reasons: list[str],
    entities_changed: list[dict[str, object]],
) -> DecisionOutcome:
    """Classify the completion as failed, already satisfied, or completed."""
    if failed:
        return DecisionOutcome(
            scenario=scenario,
            action_type="charge_completion_failed",
            summary=f"{scenario} failed",
            reason="; ".join(reasons),
            details=details,
            entities_changed=entities_changed,
        )
    if not entities_changed:
        return DecisionOutcome(
            scenario=scenario,
            action_type="no_action",
            summary="Program SOC already at its Normal SOC Target",
            reason="Completion target already present",
            details=details,
        )
    return DecisionOutcome(
        scenario=scenario,
        action_type="charge_completed",
        summary="Programs returned to their Normal SOC Target",
        details=details,
        entities_changed=entities_changed,
    )


async def _async_complete_program_set(
    hass: HomeAssistant,
    entry: ConfigEntry,
    store: Store,
    plan: dict[str, Any],
    restore_targets: dict[str, float],
    context: Context,
    scenario: str,
) -> None:
    """Return each recorded program to its Normal SOC Target, independently.

    A program that fails is retried alone after five minutes; programs already
    restored are left as they are.
    """
    pending, failures, reasons = _read_completion_state(hass, restore_targets)
    entities_changed = await _restore_programs(
        hass, entry, context, pending, failures, reasons
    )
    details = {
        "programs": [
            {"entity_id": entity_id, "soc": soc}
            for entity_id, soc in restore_targets.items()
        ],
        "window_start": plan.get("window_start"),
        "window_end": plan.get("window_end"),
    }
    async with active_decision_audit(
        hass, entry, trigger="scheduler:morning_charge_completion"
    ):
        outcome = _program_set_outcome(
            scenario, details, bool(failures), reasons, entities_changed
        )
        await log_decision_unified(
            hass, entry, outcome, context=context, logger=_LOGGER
        )

        window_start = dt_util.parse_datetime(str(plan["window_start"]))
        window_end = dt_util.parse_datetime(str(plan["window_end"]))
        if failures and window_start is not None and window_end is not None:
            await async_schedule_charge_completion(
                hass,
                entry,
                charge_type="morning",
                complete_at=dt_util.now() + timedelta(minutes=5),
                window_start=dt_util.as_local(window_start),
                window_end=dt_util.as_local(window_end),
                window_source=plan.get("window_source"),
                restore_targets=failures,
            )
            return
        if failures:
            _LOGGER.error(
                "Cannot retry morning charge completion with invalid window data"
            )

        await store.async_remove()
        _plans(hass, entry).pop("morning", None)
        _publish_schedule_snapshot(hass, entry)


async def _async_restore_charge_completion(
    hass: HomeAssistant,
    entry: ConfigEntry,
    charge_type: ChargeType,
) -> None:
    """Restore one persisted completion plan without taking the Morning lock."""
    now = dt_util.now()
    store = _store(hass, entry, charge_type)
    plan = await store.async_load()
    if not isinstance(plan, dict):
        return
    complete_at = dt_util.parse_datetime(str(plan.get("complete_at")))
    window_start = dt_util.parse_datetime(str(plan.get("window_start")))
    window_end = dt_util.parse_datetime(str(plan.get("window_end")))
    if complete_at is None or window_start is None or window_end is None:
        _LOGGER.error("Invalid persisted %s charge completion plan", charge_type)
        await store.async_remove()
        _plans(hass, entry).pop(charge_type, None)
        _publish_schedule_snapshot(hass, entry)
        return
    complete_at = dt_util.as_local(complete_at)
    window_start = dt_util.as_local(window_start)
    window_end = dt_util.as_local(window_end)
    if dt_util.as_utc(complete_at) <= dt_util.as_utc(now):
        _plans(hass, entry)[charge_type] = plan
        await _async_handle_charge_completion(hass, entry, charge_type)
    else:
        await async_schedule_charge_completion(
            hass,
            entry,
            charge_type=charge_type,
            complete_at=complete_at,
            window_start=window_start,
            window_end=window_end,
            window_source=plan.get("window_source"),
            restore_targets=plan_restore_targets(plan) or None,
        )


async def async_restore_charge_completions(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Restore pending completion listeners and run overdue plans."""
    for charge_type in ("morning", "afternoon"):
        if charge_type == "morning":
            async with morning_charge_lock(hass, entry):
                await _async_restore_charge_completion(hass, entry, charge_type)
        else:
            await _async_restore_charge_completion(hass, entry, charge_type)


def cancel_charge_completion_listeners(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Cancel runtime completion listeners without removing persisted plans."""
    listeners = _listeners(hass, entry)
    for remove_listener in list(listeners.values()):
        remove_listener()
    listeners.clear()
