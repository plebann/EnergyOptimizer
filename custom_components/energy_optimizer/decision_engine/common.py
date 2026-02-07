"""Shared helpers for decision engine modules."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..const import CONF_BATTERY_SOC_SENSOR, CONF_PROG2_SOC_ENTITY, DOMAIN
from ..helpers import get_required_float_state

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def resolve_entry(hass: HomeAssistant, entry_id: str | None) -> ConfigEntry | None:
    """Resolve a config entry for the integration.

    If entry_id is provided, validates and returns the matching entry.
    If entry_id is None, returns the single entry if exactly one exists.
    """
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            _LOGGER.error("Invalid entry_id '%s' for %s", entry_id, DOMAIN)
            return None
        return entry

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        _LOGGER.error("No Energy Optimizer configuration found")
        return None
    if len(entries) > 1:
        _LOGGER.error(
            "Multiple %s config entries exist; service call must include entry_id",
            DOMAIN,
        )
        return None

    return entries[0]


def get_required_prog2_soc_state(
    hass: HomeAssistant, config: dict[str, object]
) -> tuple[str, float] | None:
    """Return Program 2 SOC entity id and value when available."""
    prog2_soc_entity = config.get(CONF_PROG2_SOC_ENTITY)
    prog2_soc_value = get_required_float_state(
        hass,
        prog2_soc_entity,
        entity_name="Program 2 SOC entity",
    )
    if prog2_soc_value is None:
        return None
    return str(prog2_soc_entity), prog2_soc_value


def get_required_current_soc_state(
    hass: HomeAssistant, config: dict[str, object]
) -> tuple[str, float] | None:
    """Return battery SOC entity id and value when available."""
    battery_soc_entity = config.get(CONF_BATTERY_SOC_SENSOR)
    current_soc = get_required_float_state(
        hass,
        battery_soc_entity,
        entity_name="Battery SOC sensor",
    )
    if current_soc is None:
        return None
    return str(battery_soc_entity), current_soc
