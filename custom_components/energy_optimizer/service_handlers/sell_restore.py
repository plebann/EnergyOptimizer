"""Sell restore handler."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import Context
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_EXPORT_POWER_ENTITY,
    CONF_MAX_EXPORT_POWER,
    CONF_PROG3_SOC_ENTITY,
    CONF_PROG5_SOC_ENTITY,
    CONF_WORK_MODE_ENTITY,
    DEFAULT_MAX_EXPORT_POWER,
    DOMAIN,
    STORAGE_KEY_SELL_RESTORE,
    STORAGE_VERSION_SELL_RESTORE,
    WORK_MODE_ZERO_EXPORT_TO_LOAD,
)
from ..controllers.inverter import (
    set_discharge_current,
    set_export_power,
    set_program_soc,
    set_work_mode,
)
from ..utils.decision_dump import active_decision_audit, emit_decision_dump, record_step

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_handle_sell_restore(
    hass: HomeAssistant,
    entry: ConfigEntry,
    sell_type: str,
) -> None:
    """Restore inverter state after a sell window."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    restore = entry_data.get("sell_restore")
    store = Store(
        hass,
        STORAGE_VERSION_SELL_RESTORE,
        f"{STORAGE_KEY_SELL_RESTORE}.{entry.entry_id}",
    )

    if not restore:
        restore = await store.async_load()

    if not restore or restore.get("sell_type") != sell_type:
        return

    _LOGGER.info("Restoring inverter state after %s sell", sell_type)
    integration_context = Context()
    work_mode_entity = entry.data.get(CONF_WORK_MODE_ENTITY)

    async with active_decision_audit(
        hass, entry, trigger=f"scheduler:{sell_type}_sell_restore"
    ) as audit:
        if restore.get("work_mode"):
            work_mode = restore["work_mode"]
        else:
            work_mode = WORK_MODE_ZERO_EXPORT_TO_LOAD

        await set_work_mode(
            hass,
            str(work_mode_entity) if work_mode_entity else None,
            str(work_mode),
            entry=entry,
            logger=_LOGGER,
            context=integration_context,
        )

        restore_prog_soc_entity = restore.get("prog_soc_entity")
        if restore_prog_soc_entity:
            prog_soc_entity = str(restore_prog_soc_entity)
        elif sell_type == "evening":
            prog_soc_entity = entry.data.get(CONF_PROG5_SOC_ENTITY)
        else:
            prog_soc_entity = entry.data.get(CONF_PROG3_SOC_ENTITY)

        if restore.get("prog_soc_value") is not None:
            prog_soc_value = restore["prog_soc_value"]
        else:
            prog_soc_value = 11

        if prog_soc_entity is not None and prog_soc_value is not None:
            await set_program_soc(
                hass,
                str(prog_soc_entity),
                float(prog_soc_value),
                entry=entry,
                logger=_LOGGER,
                context=integration_context,
            )

        regulator = restore.get("regulator")
        if isinstance(regulator, dict):
            kind = regulator.get("kind")
            entity_id = regulator.get("entity_id")
            value = regulator.get("value")
            record_step(
                "sell_restore_regulator",
                kind="restore",
                inputs={"kind": kind, "entity_id": entity_id, "value": value},
                result="requested",
            )
            if kind == "discharge_current":
                await set_discharge_current(
                    hass,
                    str(entity_id) if entity_id else None,
                    float(value),
                    entry=entry,
                    logger=_LOGGER,
                    context=integration_context,
                )
            elif kind == "export_power":
                await set_export_power(
                    hass,
                    str(entity_id) if entity_id else None,
                    float(value),
                    entry=entry,
                    logger=_LOGGER,
                    context=integration_context,
                )
        else:
            export_power_entity = entry.data.get(CONF_EXPORT_POWER_ENTITY)
            max_export_power = float(
                entry.data.get(
                    CONF_MAX_EXPORT_POWER,
                    entry.data.get("inverter_max_power", DEFAULT_MAX_EXPORT_POWER),
                )
            )
            if export_power_entity:
                await set_export_power(
                    hass,
                    str(export_power_entity),
                    max_export_power,
                    entry=entry,
                    logger=_LOGGER,
                    context=integration_context,
                )

        emit_decision_dump(
            _LOGGER,
            audit,
            {
                "scenario": f"{sell_type.title()} Peak Sell Restore",
                "action_type": "sell_restore",
                "summary": "Restored inverter settings after sell window",
            },
        )

    entry_data.pop("sell_restore", None)
    await store.async_remove()


async def async_check_pending_sell_restore(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Check pending restore data after startup and run overdue restore."""
    store = Store(
        hass,
        STORAGE_VERSION_SELL_RESTORE,
        f"{STORAGE_KEY_SELL_RESTORE}.{entry.entry_id}",
    )
    data = await store.async_load()
    if not data:
        return

    now = dt_util.as_local(dt_util.utcnow())
    restore_hour = int(data.get("restore_hour", 0))
    sell_time_raw = data.get("timestamp")
    sell_time = dt_util.parse_datetime(str(sell_time_raw)) if sell_time_raw else None

    if sell_time and (
        now.date() > sell_time.date()
        or (now.date() == sell_time.date() and now.hour >= restore_hour)
    ):
        _LOGGER.info("Startup: executing overdue sell restore for %s", data.get("sell_type"))
        await async_handle_sell_restore(hass, entry, str(data.get("sell_type")))
        return

    hass.data[DOMAIN][entry.entry_id]["sell_restore"] = data
