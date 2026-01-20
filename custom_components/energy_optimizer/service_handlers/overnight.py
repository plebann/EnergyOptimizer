"""Overnight schedule service handler."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.core import ServiceCall
from homeassistant.util import dt as dt_util

from ..calculations.battery import calculate_battery_space
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

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_handle_overnight_schedule(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle overnight_schedule service call."""

    _LOGGER.info("=== Battery Overnight Handling Started ===")

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        _LOGGER.error("No Energy Optimizer configuration found")
        return

    entry = entries[0]
    config = entry.data

    # Program SOC entity IDs reused across scenarios
    prog1_soc = config.get(CONF_PROG1_SOC_ENTITY)
    prog2_soc = config.get(CONF_PROG2_SOC_ENTITY)
    prog6_soc = config.get(CONF_PROG6_SOC_ENTITY)

    async def _set_program_soc(entity_id: str | None, value: float) -> None:
        """Set a program SOC entity if provided."""
        if not entity_id:
            return
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": entity_id, "value": value},
            blocking=True,
        )
        _LOGGER.debug("Set %s to %s%%", entity_id, value)

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
        pv_state = hass.states.get(pv_forecast_entity)
        if pv_state and pv_state.state not in ("unknown", "unavailable"):
            try:
                pv_forecast = float(pv_state.state)
            except (ValueError, TypeError) as err:
                _LOGGER.warning("Could not parse PV forecast: %s", err)

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

        await _set_program_soc(prog1_soc, max_soc)
        await _set_program_soc(prog2_soc, max_soc)
        await _set_program_soc(prog6_soc, max_soc)

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

        # Log to optimization sensors
        if "last_optimization_sensor" in hass.data[DOMAIN][entry.entry_id]:
            opt_sensor = hass.data[DOMAIN][entry.entry_id]["last_optimization_sensor"]
            opt_sensor.log_optimization(
                "Battery Balancing",
                {
                    "pv_forecast_kwh": round(pv_forecast, 2),
                    "threshold_kwh": balancing_pv_threshold,
                    "target_soc": 100,
                    "days_since_last": days_since_balancing,
                },
            )
        if "optimization_history_sensor" in hass.data[DOMAIN][entry.entry_id]:
            hist_sensor = hass.data[DOMAIN][entry.entry_id]["optimization_history_sensor"]
            hist_sensor.add_entry(
                "Battery Balancing",
                {
                    "pv_forecast": f"{pv_forecast:.1f} kWh",
                    "target": "100%",
                    "reason": f"Low PV forecast ({pv_forecast:.1f} < {balancing_pv_threshold:.1f})",
                },
            )

        # Send notification
        await hass.services.async_call(
            "notify",
            "notify",
            {"message": "Night battery balancing enabled - Up to 100%"},
            blocking=False,
        )

        _LOGGER.info("Battery balancing mode activated")
        return

    # Get current battery SOC for preservation scenarios
    _LOGGER.debug("Balancing not triggered - checking preservation/normal operation modes")
    soc_sensor = config.get(CONF_BATTERY_SOC_SENSOR)
    current_soc = None
    if soc_sensor:
        soc_state = hass.states.get(soc_sensor)
        if soc_state and soc_state.state not in ("unknown", "unavailable"):
            try:
                current_soc = float(soc_state.state)
            except (ValueError, TypeError) as err:
                _LOGGER.warning("Could not parse battery SOC: %s", err)

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

        # Lock battery at current SOC to avoid inefficient charge/discharge cycles
        if prog1_soc:
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": prog1_soc, "value": current_soc},
                blocking=True,
            )
            _LOGGER.debug("Set %s to %.1f%% (current SOC)", prog1_soc, current_soc)

        if prog6_soc:
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": prog6_soc, "value": current_soc},
                blocking=True,
            )
            _LOGGER.debug("Set %s to %.1f%% (current SOC)", prog6_soc, current_soc)

        # Log to optimization sensors
        if "last_optimization_sensor" in hass.data[DOMAIN][entry.entry_id]:
            opt_sensor = hass.data[DOMAIN][entry.entry_id]["last_optimization_sensor"]
            opt_sensor.log_optimization(
                "Battery Preservation",
                {
                    "pv_forecast_kwh": round(pv_forecast, 2),
                    "pv_with_efficiency_kwh": round(pv_with_efficiency, 2),
                    "battery_space_kwh": round(battery_space, 2),
                    "locked_soc": round(current_soc, 1),
                },
            )
        if "optimization_history_sensor" in hass.data[DOMAIN][entry.entry_id]:
            hist_sensor = hass.data[DOMAIN][entry.entry_id]["optimization_history_sensor"]
            hist_sensor.add_entry(
                "Battery Preservation",
                {
                    "pv_forecast": f"{pv_forecast:.1f} kWh",
                    "battery_space": f"{battery_space:.1f} kWh",
                    "locked_at": f"{current_soc:.0f}%",
                    "reason": f"PV too low for battery space ({pv_with_efficiency:.1f} < {battery_space:.1f})",
                },
            )

        # Send notification
        await hass.services.async_call(
            "notify",
            "notify",
            {
                "message": f"Battery preservation mode - SOC locked at {current_soc:.0f}%"
            },
            blocking=False,
        )

        _LOGGER.info("Battery preservation mode activated")
        return

    # SCENARIO 3: Normal Operation Restoration
    _LOGGER.debug("Preservation not needed - checking normal operation restoration")
    prog6_soc = config.get(CONF_PROG6_SOC_ENTITY)
    min_soc = config.get("min_soc", 15)

    current_prog6_soc = None
    if prog6_soc:
        prog6_state = hass.states.get(prog6_soc)
        if prog6_state and prog6_state.state not in ("unknown", "unavailable"):
            try:
                current_prog6_soc = float(prog6_state.state)
            except (ValueError, TypeError) as err:
                _LOGGER.warning("Could not parse prog6 SOC: %s", err)

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

        await _set_program_soc(prog1_soc, min_soc)
        await _set_program_soc(prog2_soc, min_soc)
        await _set_program_soc(prog6_soc, min_soc)

        # Log to optimization sensors
        if "last_optimization_sensor" in hass.data[DOMAIN][entry.entry_id]:
            opt_sensor = hass.data[DOMAIN][entry.entry_id]["last_optimization_sensor"]
            opt_sensor.log_optimization(
                "Normal Operation Restored",
                {
                    "previous_soc": round(current_prog6_soc, 1),
                    "restored_to_soc": min_soc,
                    "pv_forecast_kwh": round(pv_forecast, 2),
                },
            )
        if "optimization_history_sensor" in hass.data[DOMAIN][entry.entry_id]:
            hist_sensor = hass.data[DOMAIN][entry.entry_id]["optimization_history_sensor"]
            hist_sensor.add_entry(
                "Normal Operation",
                {
                    "previous": f"{current_prog6_soc:.0f}%",
                    "restored_to": f"{min_soc:.0f}%",
                    "reason": "PV within normal range",
                },
            )

        # Send notification
        await hass.services.async_call(
            "notify",
            "notify",
            {"message": f"Normal battery operation restored - SOC minimum {min_soc:.0f}%"},
            blocking=False,
        )

        _LOGGER.info("Normal operation restored")
        return

    # Log when no action taken
    if "last_optimization_sensor" in hass.data[DOMAIN][entry.entry_id]:
        opt_sensor = hass.data[DOMAIN][entry.entry_id]["last_optimization_sensor"]
        opt_sensor.log_optimization(
            "No Action",
            {
                "pv_forecast_kwh": round(pv_forecast, 2),
                "battery_space_kwh": round(battery_space, 2) if battery_space else 0,
                "current_soc": round(current_soc, 1) if current_soc else 0,
            },
        )
    if "optimization_history_sensor" in hass.data[DOMAIN][entry.entry_id]:
        hist_sensor = hass.data[DOMAIN][entry.entry_id]["optimization_history_sensor"]
        hist_sensor.add_entry(
            "No Action",
            {"reason": "No changes needed"},
        )

    _LOGGER.debug("No battery schedule changes needed")
