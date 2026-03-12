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
    CONF_WORK_MODE_ENTITY,
    DEFAULT_MAX_EXPORT_POWER,
    DOMAIN,
    STORAGE_KEY_SELL_RESTORE,
    STORAGE_VERSION_SELL_RESTORE,
    WORK_MODE_ZERO_EXPORT_TO_LOAD,
)
from ..controllers.inverter import set_export_power, set_program_soc, set_work_mode

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
    work_mode = WORK_MODE_ZERO_EXPORT_TO_LOAD
    if restore.get("work_mode"):
        work_mode_entity = entry.data.get(CONF_WORK_MODE_ENTITY)
        work_mode = restore["work_mode"]
    else:
        work_mode_entity = None
    await set_work_mode(
        hass,
        str(work_mode_entity) if work_mode_entity else None,
        str(work_mode),
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )

    prog_soc_entity = restore.get("prog_soc_entity")
    prog_soc_value = restore.get("prog_soc_value")
    if prog_soc_entity is not None and prog_soc_value is not None:
        await set_program_soc(
            hass,
            str(prog_soc_entity),
            float(prog_soc_value),
            entry=entry,
            logger=_LOGGER,
            context=integration_context,
        )

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
