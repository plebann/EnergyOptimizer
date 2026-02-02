"""Morning grid charge service handler."""
from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import ServiceCall

from ..decision_engine.morning_charge import async_run_morning_charge

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def async_handle_morning_grid_charge(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    """Handle morning_grid_charge routine."""
    await async_run_morning_charge(
        hass,
        entry_id=call.data.get("entry_id"),
        margin=call.data.get("margin"),
    )
