"""Inverter controller abstraction for Energy Optimizer."""
from __future__ import annotations

import logging
from math import ceil
from typing import TYPE_CHECKING

from custom_components.energy_optimizer.helpers import is_test_mode

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, Context
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


async def _call_service(
    hass: HomeAssistant,
    domain: str,
    service: str,
    service_data: dict,
    *,
    blocking: bool = True,
    context: Context | None = None,
) -> None:
    """Call a Home Assistant service."""
    await hass.services.async_call(
        domain,
        service,
        service_data,
        blocking=blocking,
        context=context,
    )


async def set_program_soc(
    hass: HomeAssistant,
    entity_id: str | None,
    value: float,
    *,
    entry: ConfigEntry | None = None,
    logger: logging.Logger | None = None,
    context: Context | None = None,
) -> None:
    """Set a program SOC entity if provided."""
    if not entity_id:
        return

    value = float(ceil(value))

    if entry is not None:
        if is_test_mode(entry):
            if logger:
                logger.info("Test mode enabled - skipping set_value for %s", entity_id)
            else:
                _LOGGER.info("Test mode enabled - skipping set_value for %s", entity_id)
            return

    await _call_service(
        hass,
        "number",
        "set_value",
        {"entity_id": entity_id, "value": value},
        context=context,
    )

    if logger:
        logger.debug("Set %s to %s%%", entity_id, value)
    else:
        _LOGGER.debug("Set %s to %s%%", entity_id, value)


async def set_max_charge_current(
    hass: HomeAssistant,
    entity_id: str | None,
    value: float,
    *,
    entry: ConfigEntry | None = None,
    logger: logging.Logger | None = None,
    context: Context | None = None,
) -> None:
    """Set max charge current entity if provided."""
    if not entity_id:
        return

    if entry is not None:
        if is_test_mode(entry):
            if logger:
                logger.info("Test mode enabled - skipping set_value for %s", entity_id)
            else:
                _LOGGER.info("Test mode enabled - skipping set_value for %s", entity_id)
            return

    await _call_service(
        hass,
        "number",
        "set_value",
        {"entity_id": entity_id, "value": value},
        context=context,
    )

    if logger:
        logger.debug("Set %s to %sA", entity_id, value)
    else:
        _LOGGER.debug("Set %s to %sA", entity_id, value)


async def set_charge_current(
    hass: HomeAssistant,
    entity_id: str | None,
    value: float,
    *,
    entry: ConfigEntry | None = None,
    logger: logging.Logger | None = None,
    context: Context | None = None,
) -> None:
    """Set charge current entity if provided."""
    if not entity_id:
        return

    if entry is not None:
        if is_test_mode(entry):
            if logger:
                logger.info("Test mode enabled - skipping set_value for %s", entity_id)
            else:
                _LOGGER.info("Test mode enabled - skipping set_value for %s", entity_id)
            return

    await _call_service(
        hass,
        "number",
        "set_value",
        {"entity_id": entity_id, "value": value},
        context=context,
    )

    if logger:
        logger.debug("Set %s to %sA", entity_id, value)
    else:
        _LOGGER.debug("Set %s to %sA", entity_id, value)
