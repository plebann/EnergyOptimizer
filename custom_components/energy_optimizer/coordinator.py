"""DataUpdateCoordinator for Energy Optimizer integration."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_BATTERY_SOC_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_PV_FORECAST_TODAY,
    CONF_PV_FORECAST_TOMORROW,
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
        )
        self.hass = hass
        self.entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from integration.

        Returns:
            Dictionary containing updated data for coordinator consumers.
        """
        data: dict[str, Any] = {}
        config = self.entry.data

        for key in (
            CONF_BATTERY_SOC_SENSOR,
            CONF_PRICE_SENSOR,
            CONF_PV_FORECAST_TODAY,
            CONF_PV_FORECAST_TOMORROW,
        ):
            entity_id = config.get(key)
            value, _raw, error = get_float_state_info(self.hass, entity_id)
            if error is None and value is not None:
                data[key] = value
            else:
                data[key] = None

        return data
