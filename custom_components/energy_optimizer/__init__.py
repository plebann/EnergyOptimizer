"""The Energy Optimizer integration."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, SERVICE_OVERNIGHT_SCHEDULE
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

    # Forward entry setup to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (only once, not per config entry)
    if not hass.services.has_service(DOMAIN, SERVICE_OVERNIGHT_SCHEDULE):
        await async_register_services(hass)

    # Register automatic daily overnight handling at 22:00
    async def _trigger_overnight_handling(now):
        """Trigger battery overnight handling at 22:00."""
        _LOGGER.info("Auto-triggering battery overnight handling at 22:00")
        await hass.services.async_call(
            DOMAIN,
            SERVICE_OVERNIGHT_SCHEDULE,
            {"entry_id": entry.entry_id},
            blocking=False,
        )

    # Track time change: trigger at 22:00 every day
    remove_listener = async_track_time_change(
        hass, _trigger_overnight_handling, hour=22, minute=0, second=0
    )

    # Store removal callback for cleanup
    if "listeners" not in hass.data[DOMAIN][entry.entry_id]:
        hass.data[DOMAIN][entry.entry_id]["listeners"] = []
    hass.data[DOMAIN][entry.entry_id]["listeners"].append(remove_listener)

    _LOGGER.info("Energy Optimizer: Automatic 22:00 overnight handling enabled")

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
