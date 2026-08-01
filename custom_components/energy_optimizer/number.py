"""Number entities for Energy Optimizer."""
from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEFAULT_EXPORT_BLOCK_OFFGRID_THRESHOLD, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Energy Optimizer number entities."""
    threshold = ExportBlockOffgridThresholdNumber(config_entry)
    async_add_entities([threshold])
    hass.data.setdefault(DOMAIN, {}).setdefault(config_entry.entry_id, {})[
        "export_block_offgrid_threshold"
    ] = threshold


class ExportBlockOffgridThresholdNumber(NumberEntity, RestoreEntity):
    """Configure the surplus threshold that permits off-grid export blocking."""

    _attr_has_entity_name = True
    _attr_translation_key = "export_block_offgrid_threshold"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_native_min_value = 0.0
    _attr_native_max_value = 10.0
    _attr_native_step = 0.1
    _attr_icon = "mdi:transmission-tower-export"

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the export block threshold number."""
        self._attr_unique_id = f"{config_entry.entry_id}_export_block_offgrid_threshold"
        self._attr_native_value = DEFAULT_EXPORT_BLOCK_OFFGRID_THRESHOLD
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": "Energy Optimizer",
            "manufacturer": "Energy Optimizer",
            "model": "Battery Optimizer",
        }

    async def async_added_to_hass(self) -> None:
        """Restore the last configured threshold."""
        if (last_state := await self.async_get_last_state()) is None:
            return
        try:
            value = float(last_state.state)
        except (TypeError, ValueError):
            return
        if self._attr_native_min_value <= value <= self._attr_native_max_value:
            self._attr_native_value = value

    async def async_set_native_value(self, value: float) -> None:
        """Set the surplus threshold."""
        self._attr_native_value = value
        self.async_write_ha_state()
