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
from .common import resolve_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_run_daytime_min_price_restore(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
) -> None:
    """Restore max charge current to configured default at daytime min price hour."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return

    config = entry.data
    max_charge_entity = config.get(CONF_MAX_CHARGE_CURRENT_ENTITY)
    max_charge_value, _, error = get_float_state_info(hass, max_charge_entity)
    if error is not None:
        _LOGGER.warning(
            "Daytime min price restore: cannot read max charge current (%s) — skip",
            error,
        )
        return
    if max_charge_value is None:
        _LOGGER.warning("Daytime min price restore: max charge current has no value — skip")
        return
    if max_charge_value >= DEFAULT_MAX_CHARGE_CURRENT:
        _LOGGER.debug(
            "Daytime min price restore: max charge current already %.0f — skip",
            max_charge_value,
        )
        return

    _LOGGER.info(
        "Daytime min price restore: setting max charge current to %.0f (was %.0f)",
        float(DEFAULT_MAX_CHARGE_CURRENT),
        max_charge_value,
    )

    integration_context = Context()
    work_mode_entity = config.get(CONF_WORK_MODE_ENTITY)
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

    await set_max_charge_current(
        hass,
        max_charge_entity,
        DEFAULT_MAX_CHARGE_CURRENT,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )
