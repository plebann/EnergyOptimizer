"""Overnight schedule service handler."""
from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import ServiceCall

from ..const import DOMAIN, SERVICE_OVERNIGHT_SCHEDULE
from ..decision_engine.evening_behavior import async_run_evening_behavior

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def async_handle_overnight_schedule(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    """Handle overnight_schedule service call."""
    await async_run_evening_behavior(
        hass,
        entry_id=call.data.get("entry_id"),
        trigger=f"service:{DOMAIN}.{SERVICE_OVERNIGHT_SCHEDULE}",
    )
