"""Morning grid charge decision logic."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..calculations.battery import calculate_battery_reserve, kwh_to_soc
from ..calculations.utils import build_hourly_usage_array
from ..const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_DAILY_LOSSES_SENSOR,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_PROG2_SOC_ENTITY,
    DEFAULT_BATTERY_CAPACITY_AH,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_BATTERY_VOLTAGE,
    DEFAULT_MAX_SOC,
    DEFAULT_MIN_SOC
)
from ..decision_engine.common import resolve_entry
from ..helpers import get_float_state_info, get_float_value
from ..controllers.inverter import set_program_soc
from ..utils.logging import DecisionOutcome, log_decision_unified

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, Context

_LOGGER = logging.getLogger(__name__)


async def async_run_morning_charge(
    hass: HomeAssistant, *, entry_id: str | None = None, margin: float | None = None
) -> None:
    """Run morning grid charge routine."""

    # Import Context here to avoid circular import
    from homeassistant.core import Context

    # Create integration context for this decision engine run
    integration_context = Context()

    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    config = entry.data

    prog2_soc_entity = config.get(CONF_PROG2_SOC_ENTITY)
    if not prog2_soc_entity:
        _LOGGER.error("Program 2 SOC entity not configured")
        return

    prog2_soc_value, prog2_raw, prog2_error = get_float_state_info(
        hass, prog2_soc_entity
    )
    if prog2_error is not None or prog2_soc_value is None:
        if prog2_error in ("missing", "unavailable"):
            _LOGGER.warning("Program 2 SOC entity %s unavailable", prog2_soc_entity)
        else:
            _LOGGER.warning(
                "Program 2 SOC entity %s has invalid value: %s",
                prog2_soc_entity,
                prog2_raw,
            )
        return

    if prog2_soc_value >= 100.0:
        _LOGGER.info("Program 2 SOC already at 100%%, skipping morning grid charge")
        return

    battery_soc_entity = config.get(CONF_BATTERY_SOC_SENSOR)
    if not battery_soc_entity:
        _LOGGER.error("Battery SOC sensor not configured")
        return

    current_soc, soc_raw, soc_error = get_float_state_info(hass, battery_soc_entity)
    if soc_error is not None or current_soc is None:
        if soc_error in ("missing", "unavailable"):
            _LOGGER.warning("Battery SOC sensor %s unavailable", battery_soc_entity)
        else:
            _LOGGER.warning(
                "Battery SOC sensor %s has invalid value: %s",
                battery_soc_entity,
                soc_raw,
            )
        return

    capacity_ah = config.get(CONF_BATTERY_CAPACITY_AH, DEFAULT_BATTERY_CAPACITY_AH)
    voltage = config.get(CONF_BATTERY_VOLTAGE, DEFAULT_BATTERY_VOLTAGE)
    min_soc = config.get(CONF_MIN_SOC, DEFAULT_MIN_SOC)
    max_soc = config.get(CONF_MAX_SOC, DEFAULT_MAX_SOC)
    efficiency = config.get(CONF_BATTERY_EFFICIENCY, DEFAULT_BATTERY_EFFICIENCY)
    margin = margin if margin is not None else 1.1

    reserve_kwh = calculate_battery_reserve(current_soc, min_soc, capacity_ah, voltage)

    hourly_usage = build_hourly_usage_array(
        config, hass.states.get, daily_load_fallback=None
    )

    base_usage_kwh = sum(hourly_usage[6:13])
    hours_morning = 7

    if efficiency:
        required_kwh = (base_usage_kwh / (efficiency / 100.0)) * margin
    else:
        required_kwh = 0.0

    losses_kwh = 0.0
    losses_entity = config.get(CONF_DAILY_LOSSES_SENSOR)
    if losses_entity:
        daily_losses = get_float_value(hass, losses_entity, default=0.0)
        if daily_losses:
            losses_kwh = (daily_losses / 24.0) * hours_morning * margin

    required_kwh += losses_kwh

    if required_kwh <= 0.0:
        _LOGGER.info("Required morning energy is zero or negative, skipping")
        return

    if reserve_kwh >= required_kwh:
        outcome = DecisionOutcome(
            scenario="Morning Grid Charge",
            action_type="no_action",
            summary=f"No action needed - Reserve {reserve_kwh:.1f} kWh sufficient",
            key_metrics={
                "result": "No action",
                "reserve": f"{reserve_kwh:.1f} kWh",
                "required": f"{required_kwh:.1f} kWh",
            },
            reason=f"Reserve covers requirement ({reserve_kwh:.1f} >= {required_kwh:.1f})",
            full_details={
                "reserve_kwh": round(reserve_kwh, 2),
                "required_kwh": round(required_kwh, 2),
            },
        )
        await log_decision_unified(
            hass, entry, outcome, context=integration_context, logger=_LOGGER
        )
        return

    deficit_kwh = required_kwh - reserve_kwh
    soc_delta = kwh_to_soc(deficit_kwh, capacity_ah, voltage)
    target_soc = min(current_soc + soc_delta, max_soc)

    await set_program_soc(
        hass, prog2_soc_entity, target_soc, entry=entry, logger=_LOGGER, context=integration_context
    )

    outcome = DecisionOutcome(
        scenario="Morning Grid Charge",
        action_type="charge_scheduled",
        summary=f"Set Program 2 SOC to {target_soc:.0f}%",
        key_metrics={
            "set_to": f"{target_soc:.0f}%",
            "required": f"{required_kwh:.1f} kWh",
            "reserve": f"{reserve_kwh:.1f} kWh",
            "deficit": f"{deficit_kwh:.1f} kWh",
        },
        reason=f"Battery deficit {deficit_kwh:.1f} kWh",
        full_details={
            "target_soc": round(target_soc, 1),
            "current_soc": round(current_soc, 1),
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "deficit_kwh": round(deficit_kwh, 2),
            "losses_kwh": round(losses_kwh, 2),
            "efficiency": round(efficiency, 1),
            "margin": margin,
        },
        entities_changed=[
            {"entity_id": prog2_soc_entity, "value": target_soc},
        ],
    )
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )
