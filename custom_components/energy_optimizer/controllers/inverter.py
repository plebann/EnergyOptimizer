"""Inverter controller abstraction for Energy Optimizer."""
from __future__ import annotations

import logging
from datetime import time
from math import ceil
from typing import TYPE_CHECKING

from custom_components.energy_optimizer.helpers import is_test_mode
from custom_components.energy_optimizer.utils.decision_dump import record_action

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
        record_action("set_program_soc", entity_id=None, requested=value, status="not_required")
        return

    value = float(ceil(value))

    if entry is not None:
        if is_test_mode(hass, entry):
            record_action(
                "set_program_soc",
                entity_id=entity_id,
                requested=value,
                status="skipped_test_mode",
            )
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
    record_action(
        "set_program_soc", entity_id=entity_id, requested=value, status="executed"
    )

    if logger:
        logger.debug("Set %s to %s%%", entity_id, value)
    else:
        _LOGGER.debug("Set %s to %s%%", entity_id, value)


async def set_program_start_time(
    hass: HomeAssistant,
    entity_id: str,
    value: time,
    *,
    entry: ConfigEntry | None = None,
    logger: logging.Logger | None = None,
    context: Context | None = None,
) -> None:
    """Set a writable program start-time entity."""
    if entry is not None and is_test_mode(hass, entry):
        record_action(
            "set_program_start_time",
            entity_id=entity_id,
            requested=value.isoformat(),
            status="skipped_test_mode",
        )
        return

    domain = entity_id.split(".", 1)[0]
    formatted = value.replace(second=0, microsecond=0).isoformat()
    if domain == "time":
        service = "set_value"
        service_data = {"entity_id": entity_id, "time": formatted}
    elif domain == "input_datetime":
        service = "set_datetime"
        service_data = {"entity_id": entity_id, "time": formatted}
    else:
        raise ValueError(
            f"Program start-time entity {entity_id} must be time or input_datetime"
        )

    await _call_service(
        hass,
        domain,
        service,
        service_data,
        context=context,
    )
    record_action(
        "set_program_start_time",
        entity_id=entity_id,
        requested=formatted,
        status="executed",
    )
    (logger or _LOGGER).debug("Set %s to %s", entity_id, formatted)


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
        record_action(
            "set_max_charge_current",
            entity_id=None,
            requested=value,
            status="not_required",
        )
        return

    if entry is not None:
        if is_test_mode(hass, entry):
            record_action(
                "set_max_charge_current",
                entity_id=entity_id,
                requested=value,
                status="skipped_test_mode",
            )
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
    record_action(
        "set_max_charge_current",
        entity_id=entity_id,
        requested=value,
        status="executed",
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
        record_action(
            "set_charge_current",
            entity_id=None,
            requested=value,
            status="not_required",
        )
        return

    if entry is not None:
        if is_test_mode(hass, entry):
            record_action(
                "set_charge_current",
                entity_id=entity_id,
                requested=value,
                status="skipped_test_mode",
            )
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
    record_action(
        "set_charge_current", entity_id=entity_id, requested=value, status="executed"
    )

    if logger:
        logger.debug("Set %s to %sA", entity_id, value)
    else:
        _LOGGER.debug("Set %s to %sA", entity_id, value)


async def set_discharge_current(
    hass: HomeAssistant,
    entity_id: str | None,
    value: float,
    *,
    entry: ConfigEntry | None = None,
    logger: logging.Logger | None = None,
    context: Context | None = None,
) -> None:
    """Set discharge current entity if provided."""
    if not entity_id:
        record_action(
            "set_discharge_current",
            entity_id=None,
            requested=value,
            status="not_required",
        )
        return

    if entry is not None:
        if is_test_mode(hass, entry):
            record_action(
                "set_discharge_current",
                entity_id=entity_id,
                requested=value,
                status="skipped_test_mode",
            )
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
    record_action(
        "set_discharge_current",
        entity_id=entity_id,
        requested=value,
        status="executed",
    )

    if logger:
        logger.debug("Set %s to %sA", entity_id, value)
    else:
        _LOGGER.debug("Set %s to %sA", entity_id, value)


async def set_export_power(
    hass: HomeAssistant,
    entity_id: str | None,
    value: float,
    *,
    entry: ConfigEntry | None = None,
    logger: logging.Logger | None = None,
    context: Context | None = None,
) -> None:
    """Set export power entity if provided."""
    if not entity_id:
        record_action(
            "set_export_power",
            entity_id=None,
            requested=value,
            status="not_required",
        )
        return

    if entry is not None:
        if is_test_mode(hass, entry):
            record_action(
                "set_export_power",
                entity_id=entity_id,
                requested=value,
                status="skipped_test_mode",
            )
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
    record_action(
        "set_export_power", entity_id=entity_id, requested=value, status="executed"
    )

    if logger:
        logger.debug("Set %s to %sW", entity_id, value)
    else:
        _LOGGER.debug("Set %s to %sW", entity_id, value)


async def set_work_mode(
    hass: HomeAssistant,
    entity_id: str | None,
    option: str,
    *,
    entry: ConfigEntry | None = None,
    logger: logging.Logger | None = None,
    context: Context | None = None,
) -> None:
    """Set inverter work mode option if provided."""
    if not entity_id:
        record_action("set_work_mode", entity_id=None, requested=option, status="not_required")
        return

    if entry is not None:
        if is_test_mode(hass, entry):
            record_action(
                "set_work_mode",
                entity_id=entity_id,
                requested=option,
                status="skipped_test_mode",
            )
            if logger:
                logger.info("Test mode enabled - skipping select_option for %s", entity_id)
            else:
                _LOGGER.info("Test mode enabled - skipping select_option for %s", entity_id)
            return

    await _call_service(
        hass,
        "select",
        "select_option",
        {"entity_id": entity_id, "option": option},
        context=context,
    )
    record_action("set_work_mode", entity_id=entity_id, requested=option, status="executed")

    if logger:
        logger.debug("Set %s to %s", entity_id, option)
    else:
        _LOGGER.debug("Set %s to %s", entity_id, option)


async def turn_on_switch(
    hass: HomeAssistant,
    entity_id: str | None,
    *,
    entry: ConfigEntry | None = None,
    logger: logging.Logger | None = None,
    context: Context | None = None,
) -> None:
    """Turn on switch entity if provided."""
    if not entity_id:
        record_action("turn_on_switch", entity_id=None, requested="on", status="not_required")
        return

    if entry is not None and is_test_mode(hass, entry):
        record_action(
            "turn_on_switch",
            entity_id=entity_id,
            requested="on",
            status="skipped_test_mode",
        )
        if logger:
            logger.info("Test mode enabled - skipping turn_on for %s", entity_id)
        else:
            _LOGGER.info("Test mode enabled - skipping turn_on for %s", entity_id)
        return

    await _call_service(
        hass,
        "switch",
        "turn_on",
        {"entity_id": entity_id},
        context=context,
    )
    record_action("turn_on_switch", entity_id=entity_id, requested="on", status="executed")

    if logger:
        logger.debug("Turned on %s", entity_id)
    else:
        _LOGGER.debug("Turned on %s", entity_id)


async def turn_off_switch(
    hass: HomeAssistant,
    entity_id: str | None,
    *,
    entry: ConfigEntry | None = None,
    logger: logging.Logger | None = None,
    context: Context | None = None,
) -> None:
    """Turn off switch entity if provided."""
    if not entity_id:
        record_action(
            "turn_off_switch", entity_id=None, requested="off", status="not_required"
        )
        return

    if entry is not None and is_test_mode(hass, entry):
        record_action(
            "turn_off_switch",
            entity_id=entity_id,
            requested="off",
            status="skipped_test_mode",
        )
        if logger:
            logger.info("Test mode enabled - skipping turn_off for %s", entity_id)
        else:
            _LOGGER.info("Test mode enabled - skipping turn_off for %s", entity_id)
        return

    await _call_service(
        hass,
        "switch",
        "turn_off",
        {"entity_id": entity_id},
        context=context,
    )
    record_action(
        "turn_off_switch", entity_id=entity_id, requested="off", status="executed"
    )

    if logger:
        logger.debug("Turned off %s", entity_id)
    else:
        _LOGGER.debug("Turned off %s", entity_id)
