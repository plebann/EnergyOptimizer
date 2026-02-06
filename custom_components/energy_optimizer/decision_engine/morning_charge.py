"""Morning grid charge decision logic."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..calculations.battery import (
    calculate_battery_reserve,
    calculate_expected_charge_current,
    kwh_to_soc,
)
from ..calculations.utils import build_hourly_usage_array
from ..const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_CHARGE_CURRENT_ENTITY,
    CONF_DAILY_LOSSES_SENSOR,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_PROG2_SOC_ENTITY,
    CONF_TARIFF_END_HOUR_SENSOR,
    DEFAULT_BATTERY_CAPACITY_AH,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_BATTERY_VOLTAGE,
    DEFAULT_MAX_SOC,
    DEFAULT_MIN_SOC,
)
from ..decision_engine.common import resolve_entry
from ..helpers import get_float_state_info, get_float_value
from ..controllers.inverter import set_charge_current, set_program_soc
from ..utils.logging import DecisionOutcome, log_decision_unified
from ..utils.heat_pump import async_fetch_heat_pump_forecast
from ..utils.pv_forecast import get_pv_forecast_kwh

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, Context

_LOGGER = logging.getLogger(__name__)


def _resolve_tariff_end_hour(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    default_hour: int = 13,
) -> int:
    """Resolve tariff end hour from configured sensor with fallback."""
    tariff_end_hour = default_hour
    tariff_end_entity = config.get(CONF_TARIFF_END_HOUR_SENSOR)
    if tariff_end_entity:
        tariff_end_value = get_float_value(
            hass, tariff_end_entity, default=tariff_end_hour
        )
        if tariff_end_value is not None:
            tariff_end_hour = int(tariff_end_value)
        else:
            _LOGGER.warning(
                "Tariff end hour sensor %s unavailable, using default %s",
                tariff_end_entity,
                default_hour,
            )
    else:
        _LOGGER.warning(
            "Tariff end hour sensor not configured, using default %s",
            default_hour,
        )

    if tariff_end_hour < 7 or tariff_end_hour > 24:
        _LOGGER.warning(
            "Tariff end hour %s out of range, using default %s",
            tariff_end_hour,
            default_hour,
        )
        tariff_end_hour = default_hour

    return tariff_end_hour


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

    tariff_end_hour = _resolve_tariff_end_hour(hass, config)

    hours_morning = max(tariff_end_hour - 6, 1)
    base_usage_kwh = sum(hourly_usage[6:tariff_end_hour])
    heat_pump_kwh = await async_fetch_heat_pump_forecast(
        hass, config, starting_hour=6, hours_ahead=hours_morning
    )

    pv_forecast_kwh = get_pv_forecast_kwh(
        hass,
        config,
        start_hour=6,
        end_hour=tariff_end_hour,
    )

    base_consumption_kwh = base_usage_kwh + heat_pump_kwh
    consumption_adjusted_kwh = base_consumption_kwh * margin

    losses_kwh = 0.0
    losses_entity = config.get(CONF_DAILY_LOSSES_SENSOR)
    if losses_entity:
        daily_losses = get_float_value(hass, losses_entity, default=0.0)
        if daily_losses:
            losses_kwh = (daily_losses / 24.0) * hours_morning * margin

    required_kwh = consumption_adjusted_kwh + losses_kwh

    if required_kwh <= 0.0:
        _LOGGER.info("Required morning energy is zero or negative, skipping")
        return

    deficit_kwh = required_kwh - reserve_kwh - pv_forecast_kwh
    if deficit_kwh <= 0.0:
        outcome = DecisionOutcome(
            scenario="Morning Grid Charge",
            action_type="no_action",
            summary=f"No action needed",
            reason=(
                f"Reserve + PV covers requirement ({reserve_kwh + pv_forecast_kwh:.1f} >= {required_kwh:.1f})"
            ),
            key_metrics={
                "result": "No action",
                "reserve": f"{reserve_kwh:.1f} kWh",
                "required": f"{required_kwh:.1f} kWh",
                "pv": f"{pv_forecast_kwh:.1f} kWh",
                "heat_pump": f"{heat_pump_kwh:.1f} kWh",
            },
            full_details={
                "reserve_kwh": round(reserve_kwh, 2),
                "required_kwh": round(required_kwh, 2),
                "pv_forecast_kwh": round(pv_forecast_kwh, 2),
                "heat_pump_kwh": round(heat_pump_kwh, 2),
            },
        )
        await log_decision_unified(
            hass, entry, outcome, context=integration_context, logger=_LOGGER
        )
        return

    deficit_to_charge_kwh = (
        deficit_kwh / (efficiency / 100.0) if efficiency else deficit_kwh
    )
    soc_delta = kwh_to_soc(deficit_to_charge_kwh, capacity_ah, voltage)
    target_soc = min(current_soc + soc_delta, max_soc)

    charge_current_entity = config.get(CONF_CHARGE_CURRENT_ENTITY)
    charge_current = calculate_expected_charge_current(
        deficit_to_charge_kwh,
        current_soc,
        capacity_ah,
        voltage,
    )

    await set_program_soc(
        hass,
        prog2_soc_entity,
        target_soc,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )
    await set_charge_current(
        hass,
        charge_current_entity,
        charge_current,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )

    outcome = DecisionOutcome(
        scenario="Morning Grid Charge",
        action_type="charge_scheduled",
        summary=f"Battery scheduled to charge to {target_soc:.0f}%",
        reason=(
            f"Deficit {deficit_to_charge_kwh:.1f} kWh, reserve {reserve_kwh:.1f} kWh, "
            f"required {required_kwh:.1f} kWh, PV {pv_forecast_kwh:.1f} kWh, "
            f"current {charge_current:.0f} A"
        ),
        key_metrics={
            "target": f"{target_soc:.0f}%",
            "required": f"{required_kwh:.1f} kWh",
            "reserve": f"{reserve_kwh:.1f} kWh",
            "deficit": f"{deficit_to_charge_kwh:.1f} kWh",
            "pv": f"{pv_forecast_kwh:.1f} kWh",
            "heat_pump": f"{heat_pump_kwh:.1f} kWh",
            "current": f"{charge_current:.0f} A",
        },
        full_details={
            "target_soc": round(target_soc, 1),
            "current_soc": round(current_soc, 1),
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "deficit_kwh": round(deficit_to_charge_kwh, 2),
            "deficit_raw_kwh": round(deficit_kwh, 2),
            "losses_kwh": round(losses_kwh, 2),
            "pv_forecast_kwh": round(pv_forecast_kwh, 2),
            "heat_pump_kwh": round(heat_pump_kwh, 2),
            "charge_current_a": round(charge_current, 1),
            "efficiency": round(efficiency, 1),
            "margin": margin,
        },
        entities_changed=[
            {"entity_id": prog2_soc_entity, "value": target_soc},
            {"entity_id": charge_current_entity, "value": charge_current},
        ],
    )
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )
