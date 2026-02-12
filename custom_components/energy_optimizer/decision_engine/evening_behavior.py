"""Evening behavior decision logic (overnight schedule)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from ..calculations.battery import calculate_battery_reserve, calculate_battery_space
from ..calculations.energy import calculate_losses, hourly_demand
from ..calculations.utils import build_hourly_usage_array
from ..const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BALANCING_INTERVAL_DAYS,
    CONF_BALANCING_PV_THRESHOLD,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    DOMAIN,
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_PROG1_SOC_ENTITY,
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG6_SOC_ENTITY,
    CONF_PV_FORECAST_TODAY,
    CONF_PV_FORECAST_TOMORROW,
    CONF_PV_PRODUCTION_SENSOR,
    DEFAULT_BATTERY_CAPACITY_AH,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_BATTERY_VOLTAGE,
    DEFAULT_BALANCING_INTERVAL_DAYS,
    DEFAULT_BALANCING_PV_THRESHOLD,
    DEFAULT_MAX_CHARGE_CURRENT,
    DEFAULT_MAX_SOC,
    DEFAULT_MIN_SOC,
)
from ..decision_engine.common import resolve_entry
from ..helpers import get_float_state_info
from ..controllers.inverter import set_program_soc, set_max_charge_current
from ..utils.forecast import async_get_forecasts
from ..utils.logging import DecisionOutcome, log_decision_unified

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, Context

_LOGGER = logging.getLogger(__name__)


async def async_run_evening_behavior(
    hass: HomeAssistant, *, entry_id: str | None = None
) -> None:
    """Run overnight schedule logic (22:00 behavior)."""

    _LOGGER.info("=== Battery Overnight Handling Started ===")

    # Import Context here to avoid circular import
    from homeassistant.core import Context

    # Create integration context for this decision engine run
    integration_context = Context()

    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    config = entry.data

    pv_compensation_sensor = None
    if (
        DOMAIN in hass.data
        and entry.entry_id in hass.data[DOMAIN]
        and isinstance(hass.data[DOMAIN][entry.entry_id], dict)
    ):
        pv_compensation_sensor = hass.data[DOMAIN][entry.entry_id].get(
            "pv_forecast_compensation_sensor"
        )

    pv_compensation_details: dict[str, float | None] = {}
    if pv_compensation_sensor is not None:

        def _coerce(value: object | None) -> float | None:
            if value is None:
                return None
            try:
                return float(value)
            except (ValueError, TypeError):
                return None

        previous_attrs = pv_compensation_sensor.extra_state_attributes or {}
        forecast_yesterday = _coerce(previous_attrs.get("forecast_today_kwh"))
        production_yesterday = _coerce(previous_attrs.get("production_today_kwh"))

        forecast_today = None
        forecast_today_entity = config.get(CONF_PV_FORECAST_TODAY)
        if forecast_today_entity:
            forecast_value, forecast_raw, forecast_error = get_float_state_info(
                hass, forecast_today_entity
            )
            if forecast_error is None and forecast_value is not None:
                forecast_today = forecast_value
            elif forecast_error == "invalid":
                _LOGGER.warning(
                    "Could not parse PV forecast today: %s", forecast_raw
                )

        production_today = None
        production_entity = config.get(CONF_PV_PRODUCTION_SENSOR)
        if production_entity:
            production_value, production_raw, production_error = get_float_state_info(
                hass, production_entity
            )
            if production_error is None and production_value is not None:
                production_today = production_value
            elif production_error == "invalid":
                _LOGGER.warning(
                    "Could not parse PV production today: %s", production_raw
                )

        pv_compensation_sensor.update_compensation(
            forecast_today_kwh=forecast_today,
            production_today_kwh=production_today,
            forecast_yesterday_kwh=forecast_yesterday,
            production_yesterday_kwh=production_yesterday,
        )

        updated_attrs = pv_compensation_sensor.extra_state_attributes or {}
        pv_compensation_details = {
            "pv_compensation_factor": (
                float(pv_compensation_sensor.native_value)
                if pv_compensation_sensor.native_value is not None
                else None
            ),
            "pv_comp_forecast_today_kwh": updated_attrs.get("forecast_today_kwh"),
            "pv_comp_production_today_kwh": updated_attrs.get(
                "production_today_kwh"
            ),
            "pv_comp_forecast_yesterday_kwh": updated_attrs.get(
                "forecast_yesterday_kwh"
            ),
            "pv_comp_production_yesterday_kwh": updated_attrs.get(
                "production_yesterday_kwh"
            ),
        }

    # Program SOC entity IDs reused across scenarios
    prog1_soc = config.get(CONF_PROG1_SOC_ENTITY)
    prog2_soc = config.get(CONF_PROG2_SOC_ENTITY)
    prog6_soc = config.get(CONF_PROG6_SOC_ENTITY)

    # Get sensor reference from hass.data
    last_balancing_sensor = None
    balancing_ongoing_sensor = None
    afternoon_grid_assist_sensor = None
    if (
        DOMAIN in hass.data
        and entry.entry_id in hass.data[DOMAIN]
        and isinstance(hass.data[DOMAIN][entry.entry_id], dict)
        and "last_balancing_sensor" in hass.data[DOMAIN][entry.entry_id]
    ):
        last_balancing_sensor = hass.data[DOMAIN][entry.entry_id]["last_balancing_sensor"]
        balancing_ongoing_sensor = hass.data[DOMAIN][entry.entry_id].get(
            "balancing_ongoing_sensor"
        )
        afternoon_grid_assist_sensor = hass.data[DOMAIN][entry.entry_id].get(
            "afternoon_grid_assist_sensor"
        )
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

    if balancing_ongoing_sensor is not None:
        balancing_ongoing_sensor.set_ongoing(False)

    # SCENARIO 1: Battery Balancing Mode
    if balancing_due and pv_forecast < balancing_pv_threshold:
        if balancing_ongoing_sensor is not None:
            balancing_ongoing_sensor.set_ongoing(True)
        _LOGGER.info(
            "Activating battery balancing mode (PV forecast: %.2f kWh < %.2f kWh)",
            pv_forecast,
            balancing_pv_threshold,
        )

        # Set program SOC targets to 100%
        max_soc = config.get(CONF_MAX_SOC, DEFAULT_MAX_SOC)
        max_charge_current_entity = config.get(CONF_MAX_CHARGE_CURRENT_ENTITY)
        max_charge_current = DEFAULT_MAX_CHARGE_CURRENT

        await set_program_soc(hass, prog1_soc, max_soc, entry=entry, logger=_LOGGER, context=integration_context)
        await set_program_soc(hass, prog2_soc, max_soc, entry=entry, logger=_LOGGER, context=integration_context)
        await set_program_soc(hass, prog6_soc, max_soc, entry=entry, logger=_LOGGER, context=integration_context)
        await set_max_charge_current(
            hass, max_charge_current_entity, max_charge_current, entry=entry, logger=_LOGGER, context=integration_context
        )
        summary = "Balancing enabled"
        outcome = DecisionOutcome(
            scenario="Evening behavior",
            action_type="balancing_enabled",
            summary=summary,
            reason=f"Balancing treshold exceeded ({days_since_balancing} days)",
            key_metrics={
                "result": summary,
                "pv_forecast": f"{pv_forecast:.1f} kWh",
                "target": "100%",
                "days_since": f"{days_since_balancing} days" if days_since_balancing else "first time",
            },
            full_details={
                "pv_forecast_kwh": round(pv_forecast, 2),
                "threshold_kwh": balancing_pv_threshold,
                "target_soc": max_soc,
                "days_since_last": days_since_balancing,
                **pv_compensation_details,
            },
            entities_changed=[
                {"entity_id": prog1_soc, "value": max_soc},
                {"entity_id": prog2_soc, "value": max_soc},
                {"entity_id": prog6_soc, "value": max_soc},
                {"entity_id": max_charge_current_entity, "value": max_charge_current},
            ],
        )
        await log_decision_unified(
            hass, entry, outcome, context=integration_context, logger=_LOGGER
        )

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

    min_soc = config.get(CONF_MIN_SOC, DEFAULT_MIN_SOC)
    if current_soc < min_soc:
        _LOGGER.info(
            "Current SOC %.1f%% below minimum %.1f%%, using min_soc as lock target",
            current_soc,
            min_soc,
        )
        current_soc = min_soc

    # Calculate battery space
    capacity_ah = config.get(CONF_BATTERY_CAPACITY_AH, DEFAULT_BATTERY_CAPACITY_AH)
    voltage = config.get(CONF_BATTERY_VOLTAGE, DEFAULT_BATTERY_VOLTAGE)
    max_soc = config.get(CONF_MAX_SOC, DEFAULT_MAX_SOC)
    efficiency = config.get(CONF_BATTERY_EFFICIENCY, DEFAULT_BATTERY_EFFICIENCY)
    margin = 1.1

    reserve_kwh = calculate_battery_reserve(
        current_soc,
        min_soc,
        capacity_ah,
        voltage,
        efficiency=efficiency,
    )

    hourly_usage = build_hourly_usage_array(
        config, hass.states.get, daily_load_fallback=None
    )
    losses_hourly, _ = calculate_losses(hass, config, hours_morning=8, margin=margin)
    _, heat_pump_hourly_20_24, _, _ = (
        await async_get_forecasts(
            hass,
            config,
            start_hour=20,
            end_hour=24,
            apply_pv_efficiency=False,
            pv_compensate=True,
            entry_id=entry.entry_id,
        )
    )
    _, heat_pump_hourly_00_04, _, _ = (
        await async_get_forecasts(
            hass,
            config,
            start_hour=0,
            end_hour=4,
            apply_pv_efficiency=False,
            pv_compensate=True,
            entry_id=entry.entry_id,
        )
    )
    heat_pump_hourly = {
        **heat_pump_hourly_20_24,
        **heat_pump_hourly_00_04,
    }

    required_20_24_kwh = sum(
        hourly_demand(
            hour,
            hourly_usage=hourly_usage,
            heat_pump_hourly=heat_pump_hourly,
            losses_hourly=losses_hourly,
            margin=margin,
        )
        for hour in range(20, 24)
    )
    required_00_04_kwh = sum(
        hourly_demand(
            hour,
            hourly_usage=hourly_usage,
            heat_pump_hourly=heat_pump_hourly,
            losses_hourly=losses_hourly,
            margin=margin,
        )
        for hour in range(0, 4)
    )
    required_to_04_kwh = required_20_24_kwh + required_00_04_kwh

    reserve_insufficient = reserve_kwh < required_to_04_kwh
    grid_assist_on = bool(afternoon_grid_assist_sensor and afternoon_grid_assist_sensor.is_on)

    battery_space = calculate_battery_space(current_soc, max_soc, capacity_ah, voltage)
    pv_with_efficiency = pv_forecast * 0.9  # 90% efficiency factor

    _LOGGER.debug(
        "Battery space: %.2f kWh, PV forecast (90%%): %.2f kWh",
        battery_space,
        pv_with_efficiency,
    )
    _LOGGER.debug(
        "Reserve until 04:00: reserve=%.2f kWh, required=%.2f kWh, grid_assist=%s",
        reserve_kwh,
        required_to_04_kwh,
        grid_assist_on,
    )

    # SCENARIO 2: Battery Preservation Mode
    if grid_assist_on or reserve_insufficient or pv_with_efficiency < battery_space:
        reasons = []
        if grid_assist_on:
            reasons.append("afternoon_grid_assist")
        if reserve_insufficient:
            reasons.append("reserve_insufficient")
        if pv_with_efficiency < battery_space:
            reasons.append("pv_insufficient")
        reason_detail = ", ".join(reasons) if reasons else "preservation_required"
        _LOGGER.info(
            "Activating battery preservation mode (PV %.2f kWh < space %.2f kWh)",
            pv_with_efficiency,
            battery_space,
        )

        await set_program_soc(hass, prog1_soc, current_soc, entry=entry, logger=_LOGGER, context=integration_context)
        await set_program_soc(hass, prog6_soc, current_soc, entry=entry, logger=_LOGGER, context=integration_context)
        summary = "Battery preservation mode"
        outcome = DecisionOutcome(
            scenario="Evening behavior",
            action_type="preservation_enabled",
            summary=summary,
            reason=(
                f"SOC locked at {current_soc:.0f}%, PV: {pv_with_efficiency:.1f}, "
                f"battery space: {battery_space:.1f}, reason: {reason_detail}"
            ),
            key_metrics={
                "result": summary,
                "pv_forecast": f"{pv_forecast:.1f} kWh",
                "battery_space": f"{battery_space:.1f} kWh",
                "reserve": f"{reserve_kwh:.1f} kWh",
                "required_to_04": f"{required_to_04_kwh:.1f} kWh",
                "target": f"{current_soc:.0f}%",
            },
            full_details={
                "pv_forecast_kwh": round(pv_forecast, 2),
                "pv_with_efficiency_kwh": round(pv_with_efficiency, 2),
                "battery_space_kwh": round(battery_space, 2),
                "reserve_kwh": round(reserve_kwh, 2),
                "required_to_04_kwh": round(required_to_04_kwh, 2),
                "reserve_insufficient": reserve_insufficient,
                "afternoon_grid_assist": grid_assist_on,
                "current_soc": round(current_soc, 1),
                "target_soc": round(current_soc, 1),
                **pv_compensation_details,
            },
            entities_changed=[
                {"entity_id": prog1_soc, "value": current_soc},
                {"entity_id": prog6_soc, "value": current_soc},
            ],
        )
        await log_decision_unified(
            hass, entry, outcome, context=integration_context, logger=_LOGGER
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

    if current_prog6_soc is not None and current_prog6_soc > min_soc:
        _LOGGER.info(
            "Restoring normal operation (current: %.0f%%, restoring to: %.0f%%)",
            current_prog6_soc,
            min_soc,
        )

        await set_program_soc(hass, prog1_soc, min_soc, entry=entry, logger=_LOGGER, context=integration_context)
        await set_program_soc(hass, prog2_soc, min_soc, entry=entry, logger=_LOGGER, context=integration_context)
        await set_program_soc(hass, prog6_soc, min_soc, entry=entry, logger=_LOGGER, context=integration_context)

        summary = "Normal operation restored"
        outcome = DecisionOutcome(
            scenario="Evening behavior",
            action_type="normal_restored",
            summary=summary,
            reason=f"PV within normal range, SOC minimum {min_soc:.0f}%",
            key_metrics={
                "result": summary,
                "previous": f"{current_prog6_soc:.0f}%",
                "target": f"{min_soc:.0f}%",
                "pv_forecast": f"{pv_forecast:.1f} kWh",
                "battery_space": f"{battery_space:.1f} kWh",
                "pv_with_efficiency": f"{pv_with_efficiency:.1f} kWh",
                "reserve": f"{reserve_kwh:.1f} kWh",
                "required_to_04": f"{required_to_04_kwh:.1f} kWh",
            },
            full_details={
                "previous_soc": round(current_prog6_soc, 1),
                "target_soc": min_soc,
                "pv_forecast_kwh": round(pv_forecast, 2),
                "reserve_kwh": round(reserve_kwh, 2),
                "required_to_04_kwh": round(required_to_04_kwh, 2),
                "reserve_insufficient": reserve_insufficient,
                "afternoon_grid_assist": grid_assist_on,
            },
            entities_changed=[
                {"entity_id": prog1_soc, "value": min_soc},
                {"entity_id": prog2_soc, "value": min_soc},
                {"entity_id": prog6_soc, "value": min_soc},
            ],
        )
        await log_decision_unified(
            hass, entry, outcome, context=integration_context, logger=_LOGGER
        )

        _LOGGER.info("Normal operation restored")
        return

    summary = "No action"
    outcome = DecisionOutcome(
        scenario="Evening behavior",
        action_type="no_action",
        summary=summary,
        reason="Battery state within acceptable parameters",
        key_metrics={
            "result": summary,
        },
        full_details={
            "pv_forecast_kwh": round(pv_forecast, 2),
            "battery_space_kwh": round(battery_space, 2) if battery_space else 0,
            "target_soc": round(current_soc, 1) if current_soc else 0,
            "reserve_kwh": round(reserve_kwh, 2),
            "required_to_04_kwh": round(required_to_04_kwh, 2),
            "reserve_insufficient": reserve_insufficient,
            "afternoon_grid_assist": grid_assist_on,
            **pv_compensation_details,
        },
    )
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )

    _LOGGER.debug("No battery schedule changes needed")
