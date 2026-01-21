"""Morning grid charge service handler."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import ServiceCall

from ..calculations.battery import calculate_battery_reserve, kwh_to_soc
from ..calculations.utils import safe_float
from ..const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_DAILY_LOSSES_SENSOR,
    CONF_LOAD_USAGE_04_08,
    CONF_LOAD_USAGE_08_12,
    CONF_LOAD_USAGE_12_16,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_PROG2_SOC_ENTITY,
    DEFAULT_BATTERY_CAPACITY_AH,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_BATTERY_VOLTAGE,
    DEFAULT_MAX_SOC,
    DEFAULT_MIN_SOC,
    DOMAIN,
)
from .control import set_program_soc
from .logging import get_logging_sensors, log_decision, notify_user

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_handle_morning_grid_charge(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle morning_grid_charge routine."""

    entry_id = call.data.get("entry_id")
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            _LOGGER.error("Invalid entry_id '%s' for %s", entry_id, DOMAIN)
            return
    else:
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No Energy Optimizer configuration found")
            return
        if len(entries) > 1:
            _LOGGER.error(
                "Multiple %s config entries exist; service call must include entry_id",
                DOMAIN,
            )
            return
        entry = entries[0]
    config = entry.data

    opt_sensor, hist_sensor = get_logging_sensors(hass, entry.entry_id)

    prog2_soc_entity = config.get(CONF_PROG2_SOC_ENTITY)
    if not prog2_soc_entity:
        _LOGGER.error("Program 2 SOC entity not configured")
        return

    prog2_state = hass.states.get(prog2_soc_entity)
    if not prog2_state or prog2_state.state in (None, "unknown", "unavailable"):
        _LOGGER.warning("Program 2 SOC entity %s unavailable", prog2_soc_entity)
        return

    try:
        prog2_soc_value = float(prog2_state.state)
    except (ValueError, TypeError):
        _LOGGER.warning(
            "Program 2 SOC entity %s has invalid value: %s",
            prog2_soc_entity,
            prog2_state.state,
        )
        return

    if prog2_soc_value >= 100.0:
        _LOGGER.info("Program 2 SOC already at 100%%, skipping morning grid charge")
        return

    battery_soc_entity = config.get(CONF_BATTERY_SOC_SENSOR)
    if not battery_soc_entity:
        _LOGGER.error("Battery SOC sensor not configured")
        return

    soc_state = hass.states.get(battery_soc_entity)
    if not soc_state or soc_state.state in (None, "unknown", "unavailable"):
        _LOGGER.warning("Battery SOC sensor %s unavailable", battery_soc_entity)
        return

    try:
        current_soc = float(soc_state.state)
    except (ValueError, TypeError):
        _LOGGER.warning(
            "Battery SOC sensor %s has invalid value: %s",
            battery_soc_entity,
            soc_state.state,
        )
        return

    capacity_ah = config.get(CONF_BATTERY_CAPACITY_AH, DEFAULT_BATTERY_CAPACITY_AH)
    voltage = config.get(CONF_BATTERY_VOLTAGE, DEFAULT_BATTERY_VOLTAGE)
    min_soc = config.get(CONF_MIN_SOC, DEFAULT_MIN_SOC)
    max_soc = config.get(CONF_MAX_SOC, DEFAULT_MAX_SOC)
    efficiency = config.get(CONF_BATTERY_EFFICIENCY, DEFAULT_BATTERY_EFFICIENCY)
    margin = call.data.get("margin", 1.1)

    reserve_kwh = calculate_battery_reserve(current_soc, min_soc, capacity_ah, voltage)

    def _read_usage(conf_key: str) -> float:
        entity_id = config.get(conf_key)
        if not entity_id:
            return 0.0
        state = hass.states.get(entity_id)
        if not state or state.state in (None, "unknown", "unavailable"):
            return 0.0
        return safe_float(state.state, 0.0)

    lu0408 = _read_usage(CONF_LOAD_USAGE_04_08)
    lu0812 = _read_usage(CONF_LOAD_USAGE_08_12)
    lu1216 = _read_usage(CONF_LOAD_USAGE_12_16)

    base_usage_kwh = (2 * lu0408) + (4 * lu0812) + (1 * lu1216)
    hours_morning = 7

    if efficiency:
        required_kwh = (base_usage_kwh / (efficiency / 100.0)) * margin
    else:
        required_kwh = 0.0

    losses_kwh = 0.0
    losses_entity = config.get(CONF_DAILY_LOSSES_SENSOR)
    if losses_entity:
        loss_state = hass.states.get(losses_entity)
        if loss_state and loss_state.state not in (None, "unknown", "unavailable"):
            daily_losses = safe_float(loss_state.state, 0.0)
            losses_kwh = (daily_losses / 24.0) * hours_morning * margin

    required_kwh += losses_kwh

    if required_kwh <= 0.0:
        _LOGGER.info("Required morning energy is zero or negative, skipping")
        return

    if reserve_kwh >= required_kwh:
        _LOGGER.info(
            "Battery reserve covers morning need (reserve %.2f kWh >= required %.2f kWh)",
            reserve_kwh,
            required_kwh,
        )

        log_decision(
            opt_sensor,
            hist_sensor,
            "Morning Grid Charge - No Action",
            {
                "reserve_kwh": round(reserve_kwh, 2),
                "required_kwh": round(required_kwh, 2),
                "lu_04_08": round(lu0408, 2),
                "lu_08_12": round(lu0812, 2),
                "lu_12_16": round(lu1216, 2),
            },
            history_scenario="Morning Grid Charge",
            history_details={
                "result": "No action",
                "reserve": f"{reserve_kwh:.1f} kWh",
                "required": f"{required_kwh:.1f} kWh",
            },
        )

        await notify_user(
            hass,
            f"Morning grid charge: no action (reserve {reserve_kwh:.1f} kWh >= required {required_kwh:.1f} kWh)",
        )
        return

    deficit_kwh = required_kwh - reserve_kwh
    soc_delta = kwh_to_soc(deficit_kwh, capacity_ah, voltage)
    target_soc = min(current_soc + soc_delta, max_soc)

    await set_program_soc(hass, prog2_soc_entity, target_soc, logger=_LOGGER)

    _LOGGER.info(
        "Morning grid charge set Program 2 SOC to %.1f%% (current SOC %.1f%%, reserve %.2f kWh, required %.2f kWh)",
        target_soc,
        current_soc,
        reserve_kwh,
        required_kwh,
    )

    log_decision(
        opt_sensor,
        hist_sensor,
        "Morning Grid Charge",
        {
            "target_soc": round(target_soc, 1),
            "current_soc": round(current_soc, 1),
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "deficit_kwh": round(deficit_kwh, 2),
            "lu_04_08": round(lu0408, 2),
            "lu_08_12": round(lu0812, 2),
            "lu_12_16": round(lu1216, 2),
            "losses_kwh": round(losses_kwh, 2),
            "efficiency": round(efficiency, 1),
            "margin": margin,
        },
        history_details={
            "set_to": f"{target_soc:.0f}%",
            "required": f"{required_kwh:.1f} kWh",
            "reserve": f"{reserve_kwh:.1f} kWh",
            "deficit": f"{deficit_kwh:.1f} kWh",
        },
    )

    await notify_user(
        hass,
        f"Morning grid charge set Program 2 SOC to {target_soc:.0f}%",
    )
