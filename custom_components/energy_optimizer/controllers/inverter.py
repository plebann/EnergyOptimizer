"""Inverter controller abstraction for Energy Optimizer."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


async def set_program_soc(
    hass: HomeAssistant,
    entity_id: str | None,
    value: float,
    *,
    entry: ConfigEntry | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Set a program SOC entity if provided."""
    if not entity_id:
        return

    if entry is not None:
        from ..helpers import is_test_mode

        if is_test_mode(entry):
            if logger:
                logger.info("Test mode enabled - skipping set_value for %s", entity_id)
            else:
                _LOGGER.info("Test mode enabled - skipping set_value for %s", entity_id)
            return

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entity_id, "value": value},
        blocking=True,
    )

    if logger:
        logger.debug("Set %s to %s%%", entity_id, value)
    else:
        _LOGGER.debug("Set %s to %s%%", entity_id, value)
