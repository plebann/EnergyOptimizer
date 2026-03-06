"""Hourly export blocking/unblocking based on current sell price."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import Context

from ..const import CONF_INVERTER_EXPORT_SURPLUS_SWITCH, CONF_PRICE_SENSOR
from ..controllers.inverter import turn_off_switch, turn_on_switch
from ..helpers import get_required_float_state
from .common import resolve_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_run_export_block_control(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
) -> None:
    """Block export when price is negative and unblock when positive."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    config = entry.data

    price = get_required_float_state(
        hass,
        config.get(CONF_PRICE_SENSOR),
        entity_name="Price sensor",
    )
    if price is None:
        return

    export_surplus_switch = config.get(CONF_INVERTER_EXPORT_SURPLUS_SWITCH)
    if not export_surplus_switch:
        _LOGGER.debug("Export block control: inverter export surplus switch not configured — skip")
        return

    switch_state = hass.states.get(str(export_surplus_switch))
    if switch_state is None:
        _LOGGER.warning(
            "Export block control: switch entity %s unavailable — skip",
            export_surplus_switch,
        )
        return

    is_enabled = str(switch_state.state).lower() == "on"

    if price < 0 and is_enabled:
        _LOGGER.info(
            "Export block control: blocking export (price %.4f, switch on -> off)",
            price,
        )
        await turn_off_switch(
            hass,
            str(export_surplus_switch),
            entry=entry,
            logger=_LOGGER,
            context=Context(),
        )
        return

    if price > 0 and not is_enabled:
        _LOGGER.info(
            "Export block control: unblocking export (price %.4f, switch off -> on)",
            price,
        )
        await turn_on_switch(
            hass,
            str(export_surplus_switch),
            entry=entry,
            logger=_LOGGER,
            context=Context(),
        )
        return

    _LOGGER.debug(
        "Export block control: no change (price %.4f, switch is %s)",
        price,
        "on" if is_enabled else "off",
    )
