"""The Energy Optimizer integration."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback

from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import EnergyOptimizerCoordinator
from .scheduler.action_scheduler import ActionScheduler
from .services import async_register_services

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry to preserve entity registry stability."""

    _LOGGER.debug("Migrating %s entry from version %s", DOMAIN, entry.version)

    if entry.version == 1:
        old_unique_ids = {
            "battery_reserve",
            "battery_space",
            "battery_capacity",
            "usable_capacity",
            "last_balancing_timestamp",
            "last_optimization",
            "optimization_history",
            "battery_capacity_ah",
            "battery_voltage_config",
            "battery_efficiency_config",
            "min_soc_config",
            "max_soc_config",
        }

        entry_id = entry.entry_id

        @callback
        def _migrate_unique_id(entity_entry: er.RegistryEntry) -> dict[str, str] | None:
            unique_id = str(entity_entry.unique_id)
            if unique_id.startswith(f"{entry_id}_"):
                return None
            if unique_id not in old_unique_ids:
                return None
            return {"new_unique_id": f"{entry_id}_{unique_id}"}

        await er.async_migrate_entries(hass, entry.entry_id, _migrate_unique_id)
        hass.config_entries.async_update_entry(entry, version=2)

    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Energy Optimizer component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Optimizer from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {})

    coordinator = EnergyOptimizerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id]["coordinator"] = coordinator

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
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
