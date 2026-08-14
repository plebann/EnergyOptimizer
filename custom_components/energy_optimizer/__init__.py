"""The Energy Optimizer integration."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, SERVICE_OVERNIGHT_SCHEDULE
from .coordinator import EnergyOptimizerCoordinator
from .scheduler.action_scheduler import ActionScheduler
from .services import async_register_services
from .utils.decision_dump import emit_config_snapshot

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Energy Optimizer component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Optimizer from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {})

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    coordinator = EnergyOptimizerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id]["coordinator"] = coordinator
    emit_config_snapshot(hass, entry)

    # Forward entry setup to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (only once, not per config entry)
    if not hass.services.has_service(DOMAIN, SERVICE_OVERNIGHT_SCHEDULE):
        await async_register_services(hass)

    # Start scheduler for fixed actions
    scheduler = ActionScheduler(hass, entry)
    scheduler.start()
    hass.data[DOMAIN][entry.entry_id]["scheduler"] = scheduler

    _LOGGER.info("Energy Optimizer scheduler enabled")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Stop scheduler
        entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
        scheduler = entry_data.get("scheduler")
        if scheduler:
            scheduler.stop()

        entry_data.pop("coordinator", None)

        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates for a config entry."""
    await async_reload_entry(hass, entry)
