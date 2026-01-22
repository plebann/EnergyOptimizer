"""Overnight schedule service handler."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import ServiceCall
from homeassistant.util import dt as dt_util

from ..calculations.battery import calculate_battery_space
from ..helpers import get_float_state_info
from ..const import (
    CONF_BALANCING_INTERVAL_DAYS,
    CONF_BALANCING_PV_THRESHOLD,
    CONF_BATTERY_SOC_SENSOR,
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_MAX_SOC,
    CONF_PROG1_SOC_ENTITY,
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG6_SOC_ENTITY,
    CONF_PV_FORECAST_TOMORROW,
    DEFAULT_BALANCING_INTERVAL_DAYS,
    DEFAULT_BALANCING_PV_THRESHOLD,
    DEFAULT_MAX_CHARGE_CURRENT,
    DEFAULT_MAX_SOC,
    DOMAIN,
)
from .control import set_program_soc
from .logging import get_logging_sensors, log_decision, notify_user

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_handle_overnight_schedule(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle overnight_schedule service call."""

    _LOGGER.info("=== Battery Overnight Handling Started ===")

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

    # Program SOC entity IDs reused across scenarios
    prog1_soc = config.get(CONF_PROG1_SOC_ENTITY)
    prog2_soc = config.get(CONF_PROG2_SOC_ENTITY)
    prog6_soc = config.get(CONF_PROG6_SOC_ENTITY)

    # Get sensor reference from hass.data
    last_balancing_sensor = None
    if (
        DOMAIN in hass.data
        and entry.entry_id in hass.data[DOMAIN]
        and isinstance(hass.data[DOMAIN][entry.entry_id], dict)
        and "last_balancing_sensor" in hass.data[DOMAIN][entry.entry_id]
    ):
        last_balancing_sensor = hass.data[DOMAIN][entry.entry_id]["last_balancing_sensor"]
    else:
        _LOGGER.warning(
            "Last balancing sensor not yet initialized. "
            "Balancing timestamp will not be updated this run."
        )

    # Read configuration
    balancing_interval_days = config.get(
        CONF_BALANCING_INTERVAL_DAYS, DEFAULT_BALANCING_INTERVAL_DAYS
    )
    balancing_pv_threshold = config.get(
        CONF_BALANCING_PV_THRESHOLD, DEFAULT_BALANCING_PV_THRESHOLD
    )

    # Check if balancing is due
    last_balancing = (
        last_balancing_sensor.native_value if last_balancing_sensor else None
    )
    days_since_balancing = None
    if last_balancing:
        days_since_balancing = (dt_util.utcnow() - last_balancing).days
        _LOGGER.debug(
            "Days since last balancing: %s (last: %s)",
            days_since_balancing,
            last_balancing,
        )

    balancing_due = (last_balancing is None) or (
        days_since_balancing >= balancing_interval_days
    )

    # Get PV forecast
    pv_forecast_entity = config.get(CONF_PV_FORECAST_TOMORROW)
    pv_forecast = 0.0
    if pv_forecast_entity:
        pv_value, pv_raw, pv_error = get_float_state_info(hass, pv_forecast_entity)
        if pv_error is None and pv_value is not None:
            pv_forecast = pv_value
        elif pv_error == "invalid":
            _LOGGER.warning("Could not parse PV forecast: %s", pv_raw)

    _LOGGER.debug(
        "Balancing check: due=%s, pv_forecast=%.2f kWh, threshold=%.2f kWh",
        balancing_due,
        pv_forecast,
        balancing_pv_threshold,
    )

    # SCENARIO 1: Battery Balancing Mode
    if balancing_due and pv_forecast < balancing_pv_threshold:
        _LOGGER.info(
            "Activating battery balancing mode (PV forecast: %.2f kWh < %.2f kWh)",
            pv_forecast,
            balancing_pv_threshold,
        )

        # Set program SOC targets to 100%
        max_soc = config.get(CONF_MAX_SOC, DEFAULT_MAX_SOC)
        max_charge_current_entity = config.get(CONF_MAX_CHARGE_CURRENT_ENTITY)
        max_charge_current = DEFAULT_MAX_CHARGE_CURRENT

        await set_program_soc(hass, prog1_soc, max_soc, logger=_LOGGER)
        await set_program_soc(hass, prog2_soc, max_soc, logger=_LOGGER)
        await set_program_soc(hass, prog6_soc, max_soc, logger=_LOGGER)

        if max_charge_current_entity:
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": max_charge_current_entity, "value": max_charge_current},
                blocking=True,
            )
            _LOGGER.debug(
                "Set %s to %sA", max_charge_current_entity, max_charge_current
            )

        log_decision(
            opt_sensor,
            hist_sensor,
            "Battery Balancing",
            {
                "pv_forecast_kwh": round(pv_forecast, 2),
                "threshold_kwh": balancing_pv_threshold,
                "target_soc": 100,
                "days_since_last": days_since_balancing,
            },
            history_details={
                "pv_forecast": f"{pv_forecast:.1f} kWh",
                "target": "100%",
                "reason": f"Low PV forecast ({pv_forecast:.1f} < {balancing_pv_threshold:.1f})",
            },
        )

        await notify_user(hass, "Night battery balancing enabled - Up to 100%")

        _LOGGER.info("Battery balancing mode activated")
        return

    # Get current battery SOC for preservation scenarios
    _LOGGER.debug("Balancing not triggered - checking preservation/normal operation modes")
    soc_sensor = config.get(CONF_BATTERY_SOC_SENSOR)
    current_soc = None
    if soc_sensor:
        soc_value, soc_raw, soc_error = get_float_state_info(hass, soc_sensor)
        if soc_error is None and soc_value is not None:
            current_soc = soc_value
        elif soc_error == "invalid":
            _LOGGER.warning("Could not parse battery SOC: %s", soc_raw)

    if current_soc is None:
        _LOGGER.warning("Current battery SOC not available, skipping preservation check")
        return

    min_soc = config.get("min_soc", 15)
    if current_soc < min_soc:
        _LOGGER.info(
            "Current SOC %.1f%% below minimum %.1f%%, using min_soc as lock target",
            current_soc,
            min_soc,
        )
        current_soc = min_soc

    # Calculate battery space
    capacity_ah = config.get("battery_capacity_ah", 200)
    voltage = config.get("battery_voltage", 48)
    max_soc = config.get("max_soc", 100)

    battery_space = calculate_battery_space(current_soc, max_soc, capacity_ah, voltage)
    pv_with_efficiency = pv_forecast * 0.9  # 90% efficiency factor

    _LOGGER.debug(
        "Battery space: %.2f kWh, PV forecast (90%%): %.2f kWh",
        battery_space,
        pv_with_efficiency,
    )

    # SCENARIO 2: Battery Preservation Mode
    if pv_with_efficiency < battery_space:
        _LOGGER.info(
            "Activating battery preservation mode (PV %.2f kWh < space %.2f kWh)",
            pv_with_efficiency,
            battery_space,
        )

        await set_program_soc(hass, prog1_soc, current_soc, logger=_LOGGER)
        await set_program_soc(hass, prog6_soc, current_soc, logger=_LOGGER)

        log_decision(
            opt_sensor,
            hist_sensor,
            "Battery Preservation",
            {
                "pv_forecast_kwh": round(pv_forecast, 2),
                "pv_with_efficiency_kwh": round(pv_with_efficiency, 2),
                "battery_space_kwh": round(battery_space, 2),
                "locked_soc": round(current_soc, 1),
            },
            history_details={
                "pv_forecast": f"{pv_forecast:.1f} kWh",
                "battery_space": f"{battery_space:.1f} kWh",
                "locked_at": f"{current_soc:.0f}%",
                "reason": f"PV too low for battery space ({pv_with_efficiency:.1f} < {battery_space:.1f})",
            },
        )

        await notify_user(
            hass, f"Battery preservation mode - SOC locked at {current_soc:.0f}%"
        )

        _LOGGER.info("Battery preservation mode activated")
        return

    # SCENARIO 3: Normal Operation Restoration
    _LOGGER.debug("Preservation not needed - checking normal operation restoration")
    prog6_soc = config.get(CONF_PROG6_SOC_ENTITY)
    min_soc = config.get("min_soc", 15)

    current_prog6_soc = None
    if prog6_soc:
        prog6_value, prog6_raw, prog6_error = get_float_state_info(hass, prog6_soc)
        if prog6_error is None and prog6_value is not None:
            current_prog6_soc = prog6_value
        elif prog6_error == "invalid":
            _LOGGER.warning("Could not parse prog6 SOC: %s", prog6_raw)

    if (
        current_prog6_soc is not None
        and current_prog6_soc > min_soc
        and not (pv_with_efficiency < battery_space)
    ):
        _LOGGER.info(
            "Restoring normal operation (current: %.0f%%, restoring to: %.0f%%)",
            current_prog6_soc,
            min_soc,
        )

        await set_program_soc(hass, prog1_soc, min_soc, logger=_LOGGER)
        await set_program_soc(hass, prog2_soc, min_soc, logger=_LOGGER)
        await set_program_soc(hass, prog6_soc, min_soc, logger=_LOGGER)

        log_decision(
            opt_sensor,
            hist_sensor,
            "Normal Operation Restored",
            {
                "previous_soc": round(current_prog6_soc, 1),
                "restored_to_soc": min_soc,
                "pv_forecast_kwh": round(pv_forecast, 2),
            },
            history_scenario="Normal Operation",
            history_details={
                "previous": f"{current_prog6_soc:.0f}%",
                "restored_to": f"{min_soc:.0f}%",
                "reason": "PV within normal range",
            },
        )

        await notify_user(
            hass,
            f"Normal battery operation restored - SOC minimum {min_soc:.0f}%",
        )

        _LOGGER.info("Normal operation restored")
        return

    log_decision(
        opt_sensor,
        hist_sensor,
        "No Action",
        {
            "pv_forecast_kwh": round(pv_forecast, 2),
            "battery_space_kwh": round(battery_space, 2) if battery_space else 0,
            "current_soc": round(current_soc, 1) if current_soc else 0,
        },
        history_details={"reason": "No changes needed"},
    )

    _LOGGER.debug("No battery schedule changes needed")
