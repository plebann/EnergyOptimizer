"""The Energy Optimizer integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_change

from .const import (
    DOMAIN,
    SERVICE_CALCULATE_CHARGE_SOC,
    SERVICE_CALCULATE_SELL_ENERGY,
    SERVICE_ESTIMATE_HEAT_PUMP,
    SERVICE_OPTIMIZE_SCHEDULE,
)
from .helpers import get_active_program_entity
from .services import async_register_services

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Energy Optimizer component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Optimizer from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {})

    # Forward entry setup to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (only once, not per config entry)
    if not hass.services.has_service(DOMAIN, SERVICE_CALCULATE_CHARGE_SOC):
        await async_register_services(hass)

    # Register automatic daily schedule optimization at 22:00
    async def _trigger_optimize_schedule(now):
        """Trigger battery schedule optimization at 22:00."""
        _LOGGER.info("Auto-triggering battery schedule optimization at 22:00")
        await hass.services.async_call(
            DOMAIN,
            SERVICE_OPTIMIZE_SCHEDULE,
            {},
            blocking=False,
        )

    # Track time change: trigger at 22:00 every day
    remove_listener = async_track_time_change(
        hass, _trigger_optimize_schedule, hour=22, minute=0, second=0
    )

    # Store removal callback for cleanup
    if "listeners" not in hass.data[DOMAIN][entry.entry_id]:
        hass.data[DOMAIN][entry.entry_id]["listeners"] = []
    hass.data[DOMAIN][entry.entry_id]["listeners"].append(remove_listener)

    _LOGGER.info("Energy Optimizer: Automatic 22:00 schedule optimization enabled")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Remove time-based listeners
        entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
        for remove_listener in entry_data.get("listeners", []):
            remove_listener()

        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
