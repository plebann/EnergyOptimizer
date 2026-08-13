"""Restore max charge current at daytime minimum-price time."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import Context

from ..const import (
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_WORK_MODE_ENTITY,
    DEFAULT_MAX_CHARGE_CURRENT,
    WORK_MODE_ZERO_EXPORT_TO_LOAD,
)
from ..controllers.inverter import set_max_charge_current, set_work_mode
from ..helpers import get_float_state_info
from ..utils.decision_dump import active_decision_audit, emit_decision_dump
from .common import resolve_entry

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_run_daytime_min_price_restore(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    trigger: str = "manual:daytime_min_price_restore",
) -> None:
    """Restore max charge current to configured default at daytime min price hour."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    async with active_decision_audit(hass, entry, trigger=trigger) as audit:
        details = await _async_run_daytime_min_price_restore(hass, entry)
        emit_decision_dump(
            _LOGGER,
            audit,
            {
                "scenario": "Daytime min price restore",
                "action_type": "restore",
                "summary": "Restored daytime inverter defaults",
                "reason": "daytime_min_price_window",
                "details": details,
            },
        )


async def _async_run_daytime_min_price_restore(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, bool]:
    """Restore configured controls after entry and audit resolution."""
    integration_context = Context()
    config = entry.data

    work_mode_entity = config.get(CONF_WORK_MODE_ENTITY)
    work_mode_restored = bool(work_mode_entity)
    if not work_mode_entity:
        _LOGGER.warning(
            "Daytime min price restore: work mode entity not configured — skip mode restore"
        )
    else:
        await set_work_mode(
            hass,
            str(work_mode_entity),
            WORK_MODE_ZERO_EXPORT_TO_LOAD,
            entry=entry,
            logger=_LOGGER,
            context=integration_context,
        )

    max_charge_entity = config.get(CONF_MAX_CHARGE_CURRENT_ENTITY)
    max_charge_current_restored = bool(max_charge_entity)
    if not max_charge_entity:
        _LOGGER.warning(
            "Daytime min price restore: max charge current entity not configured — skip charge current restore"
        )
    else:
        await set_max_charge_current(
            hass,
            max_charge_entity,
            DEFAULT_MAX_CHARGE_CURRENT,
            entry=entry,
            logger=_LOGGER,
            context=integration_context,
        )
    return {
        "work_mode_restored": work_mode_restored,
        "max_charge_current_restored": max_charge_current_restored,
    }
