"""Binary sensor platform for Energy Optimizer integration."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Energy Optimizer binary sensors from a config entry."""
    sensor = BalancingOngoingBinarySensor(config_entry)
    async_add_entities([sensor])

    hass.data.setdefault(DOMAIN, {}).setdefault(config_entry.entry_id, {})[
        "balancing_ongoing_sensor"
    ] = sensor


class BalancingOngoingBinarySensor(BinarySensorEntity, RestoreEntity):
    """Binary sensor indicating battery balancing mode."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "balancing_ongoing"
    _attr_unique_id = "balancing_ongoing"
    _attr_icon = "mdi:battery-sync"

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the binary sensor."""
        self._attr_is_on = False
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": "Energy Optimizer",
            "manufacturer": "Energy Optimizer",
            "model": "Battery Optimizer",
        }
        self._config_entry_id = config_entry.entry_id

    async def async_added_to_hass(self) -> None:
        """Restore last state when added to hass."""
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    def set_ongoing(self, ongoing: bool) -> None:
        """Update balancing ongoing state."""
        self._attr_is_on = bool(ongoing)
        self.async_write_ha_state()