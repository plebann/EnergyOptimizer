"""DataUpdateCoordinator for Energy Optimizer integration."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_BATTERY_CURRENT_SENSOR,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_PV_FORECAST_REMAINING,
    CONF_PV_FORECAST_TODAY,
    CONF_PV_FORECAST_TOMORROW,
    CONF_PV_PRODUCTION_SENSOR,
    DOMAIN,
)
from .helpers import get_float_state_info

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(minutes=5)


class EnergyOptimizerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Energy Optimizer data.

    Centralizes data updates for sensors and services.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            entry: Config entry with entity IDs
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.hass = hass
        self.entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from integration.

        Returns:
            Dictionary containing updated data for coordinator consumers.
        """
        data: dict[str, Any] = {"states": {}}
        config = self.entry.data

        entity_keys = (
            CONF_BATTERY_SOC_SENSOR,
            CONF_BATTERY_POWER_SENSOR,
            CONF_BATTERY_VOLTAGE_SENSOR,
            CONF_BATTERY_CURRENT_SENSOR,
            CONF_PRICE_SENSOR,
            CONF_PV_FORECAST_TODAY,
            CONF_PV_FORECAST_TOMORROW,
            CONF_PV_FORECAST_REMAINING,
            CONF_PV_PRODUCTION_SENSOR,
        )

        for key in entity_keys:
            entity_id = config.get(key)
            if not entity_id:
                continue
            value, _raw, error = get_float_state_info(self.hass, entity_id)
            data["states"][entity_id] = (
                value if error is None and value is not None else None
            )

        return data
