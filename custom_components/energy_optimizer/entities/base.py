"""Base entity classes for Energy Optimizer."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN


class EnergyOptimizerEntity(CoordinatorEntity):
    """Base coordinator entity for Energy Optimizer."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator,
        config_entry: ConfigEntry,
        config: dict[str, Any],
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config = config
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": "Energy Optimizer",
            "manufacturer": "Energy Optimizer",
            "model": "Battery Optimizer",
        }

        base_unique_id = getattr(self, "_attr_unique_id", None)
        if base_unique_id and isinstance(base_unique_id, str):
            prefix = f"{config_entry.entry_id}_"
            if not base_unique_id.startswith(prefix):
                self._attr_unique_id = f"{prefix}{base_unique_id}"

    def _get_state_value(self, entity_id: str | None) -> float | None:
        """Get a numeric state value from coordinator data."""
        if not entity_id or self.coordinator.data is None:
            return None
        states = self.coordinator.data.get("states")
        if not isinstance(states, dict):
            return None
        value = states.get(entity_id)
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None


class EnergyOptimizerSensor(EnergyOptimizerEntity, SensorEntity):
    """Base sensor class for Energy Optimizer."""

    pass
