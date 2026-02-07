"""Afternoon grid charge decision logic."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..calculations.battery import (
    calculate_battery_reserve,
    calculate_charge_current,
    calculate_soc_delta,
    calculate_target_soc,
)
from ..calculations.energy import calculate_losses, hourly_demand
from ..calculations.utils import build_hourly_usage_array
from ..const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_VOLTAGE,
    CONF_CHARGE_CURRENT_ENTITY,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    DEFAULT_BATTERY_CAPACITY_AH,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_BATTERY_VOLTAGE,
    DEFAULT_MAX_SOC,
    DEFAULT_MIN_SOC,
)
from ..decision_engine.common import (
    get_required_current_soc_state,
    get_required_prog2_soc_state,
    resolve_entry,
)
from ..helpers import resolve_tariff_start_hour
from ..controllers.inverter import set_charge_current, set_program_soc
from ..utils.forecast import async_get_forecasts
from ..utils.logging import DecisionOutcome, log_decision_unified

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, Context

_LOGGER = logging.getLogger(__name__)


async def async_run_afternoon_charge(
    hass: HomeAssistant, *, entry_id: str | None = None, margin: float | None = None
) -> None:
    """Run afternoon grid charge routine."""

    # Import Context here to avoid circular import
    from homeassistant.core import Context

    # Create integration context for this decision engine run
    integration_context = Context()

    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    config = entry.data

    prog2_soc_state = get_required_prog2_soc_state(hass, config)
    if prog2_soc_state is None:
        return
    prog2_soc_entity, prog2_soc_value = prog2_soc_state

    current_soc_state = get_required_current_soc_state(hass, config)
    if current_soc_state is None:
        return
    _battery_soc_entity, current_soc = current_soc_state

    capacity_ah = config.get(CONF_BATTERY_CAPACITY_AH, DEFAULT_BATTERY_CAPACITY_AH)
    voltage = config.get(CONF_BATTERY_VOLTAGE, DEFAULT_BATTERY_VOLTAGE)
    min_soc = config.get(CONF_MIN_SOC, DEFAULT_MIN_SOC)
    max_soc = config.get(CONF_MAX_SOC, DEFAULT_MAX_SOC)
    efficiency = config.get(CONF_BATTERY_EFFICIENCY, DEFAULT_BATTERY_EFFICIENCY)
    margin = margin if margin is not None else 1.1

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

    start_hour = resolve_tariff_start_hour(hass, config)
    end_hour = 22
    hours_window = max(end_hour - start_hour, 1)

    heat_pump_kwh, heat_pump_hourly, pv_forecast_kwh, pv_forecast_hourly = (
        await async_get_forecasts(
            hass,
            config,
            start_hour=start_hour,
            end_hour=end_hour,
            apply_pv_efficiency=False,
            pv_compensate=True,
        )
    )

    losses_hourly, losses_kwh = calculate_losses(
        hass, config, hours_morning=hours_window, margin=margin
    )

    required_kwh = sum(
        hourly_demand(
            hour,
            hourly_usage=hourly_usage,
            heat_pump_hourly=heat_pump_hourly,
            losses_hourly=losses_hourly,
            margin=margin,
        )
        for hour in range(start_hour, end_hour)
    )

    if required_kwh <= 0.0:
        _LOGGER.info("Required afternoon energy is zero or negative, skipping")
        return

    deficit_kwh = required_kwh - reserve_kwh - pv_forecast_kwh

    if deficit_kwh <= 0.0:
        await _handle_no_action(
            hass,
            entry,
            integration_context=integration_context,
            prog2_soc_entity=prog2_soc_entity,
            prog2_soc_value=prog2_soc_value,
            min_soc=min_soc,
            reserve_kwh=reserve_kwh,
            required_kwh=required_kwh,
            pv_forecast_kwh=pv_forecast_kwh,
            heat_pump_kwh=heat_pump_kwh,
            losses_kwh=losses_kwh,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        return

    deficit_to_charge_kwh = (
        deficit_kwh / ((efficiency / 100.0) ** 2) if efficiency else deficit_kwh
    )
    soc_delta = calculate_soc_delta(
        deficit_to_charge_kwh, capacity_ah=capacity_ah, voltage=voltage
    )
    target_soc = calculate_target_soc(current_soc, soc_delta, max_soc=max_soc)

    charge_current_entity = config.get(CONF_CHARGE_CURRENT_ENTITY)
    charge_current = calculate_charge_current(
        deficit_to_charge_kwh,
        current_soc=current_soc,
        capacity_ah=capacity_ah,
        voltage=voltage,
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

    outcome = _build_charge_outcome(
        target_soc=target_soc,
        required_kwh=required_kwh,
        reserve_kwh=reserve_kwh,
        deficit_to_charge_kwh=deficit_to_charge_kwh,
        deficit_raw_kwh=deficit_kwh,
        pv_forecast_kwh=pv_forecast_kwh,
        heat_pump_kwh=heat_pump_kwh,
        charge_current=charge_current,
        current_soc=current_soc,
        losses_kwh=losses_kwh,
        efficiency=efficiency,
        margin=margin,
        start_hour=start_hour,
        end_hour=end_hour,
    )
    outcome.entities_changed = [
        {"entity_id": prog2_soc_entity, "value": target_soc},
        {"entity_id": charge_current_entity, "value": charge_current},
    ]
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )


def _build_no_action_outcome(
    *,
    reserve_kwh: float,
    required_kwh: float,
    pv_forecast_kwh: float,
    heat_pump_kwh: float,
    losses_kwh: float,
    start_hour: int,
    end_hour: int,
) -> DecisionOutcome:
    summary = "No action needed"
    return DecisionOutcome(
        scenario="Afternoon Grid Charge",
        action_type="no_action",
        summary=summary,
        reason=(
            f"Deficit <= 0 kWh, reserve {reserve_kwh:.1f} kWh, "
            f"required {required_kwh:.1f} kWh, PV {pv_forecast_kwh:.1f} kWh"
        ),
        key_metrics={
            "result": summary,
            "reserve": f"{reserve_kwh:.1f} kWh",
            "required": f"{required_kwh:.1f} kWh",
            "pv": f"{pv_forecast_kwh:.1f} kWh",
            "heat_pump": f"{heat_pump_kwh:.1f} kWh",
            "window": f"{start_hour:02d}:00-{end_hour:02d}:00",
        },
        full_details={
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "pv_forecast_kwh": round(pv_forecast_kwh, 2),
            "heat_pump_kwh": round(heat_pump_kwh, 2),
            "losses_kwh": round(losses_kwh, 2),
            "start_hour": start_hour,
            "end_hour": end_hour,
        },
    )


async def _handle_no_action(
    hass: HomeAssistant,
    entry,
    *,
    integration_context: Context,
    prog2_soc_entity: str,
    prog2_soc_value: float,
    min_soc: float,
    reserve_kwh: float,
    required_kwh: float,
    pv_forecast_kwh: float,
    heat_pump_kwh: float,
    losses_kwh: float,
    start_hour: int,
    end_hour: int,
) -> None:
    """Handle no-action path and ensure program SOC reset."""
    await set_program_soc(
        hass,
        prog2_soc_entity,
        min_soc,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )
    outcome = _build_no_action_outcome(
        reserve_kwh=reserve_kwh,
        required_kwh=required_kwh,
        pv_forecast_kwh=pv_forecast_kwh,
        heat_pump_kwh=heat_pump_kwh,
        losses_kwh=losses_kwh,
        start_hour=start_hour,
        end_hour=end_hour,
    )
    if prog2_soc_value > min_soc:
        outcome.entities_changed = [
            {"entity_id": prog2_soc_entity, "value": min_soc}
        ]
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )


def _build_charge_outcome(
    *,
    target_soc: float,
    required_kwh: float,
    reserve_kwh: float,
    deficit_to_charge_kwh: float,
    deficit_raw_kwh: float,
    pv_forecast_kwh: float,
    heat_pump_kwh: float,
    charge_current: float,
    current_soc: float,
    losses_kwh: float,
    efficiency: float,
    margin: float,
    start_hour: int,
    end_hour: int,
) -> DecisionOutcome:
    summary = f"Battery scheduled to charge to {target_soc:.0f}%"
    return DecisionOutcome(
        scenario="Afternoon Grid Charge",
        action_type="charge_scheduled",
        summary=summary,
        reason=(
            f"Deficit {deficit_to_charge_kwh:.1f} kWh, reserve {reserve_kwh:.1f} kWh, "
            f"required {required_kwh:.1f} kWh, PV {pv_forecast_kwh:.1f} kWh, "
            f"current {charge_current:.0f} A"
        ),
        key_metrics={
            "target": f"{target_soc:.0f}%",
            "result": summary,
            "required": f"{required_kwh:.1f} kWh",
            "reserve": f"{reserve_kwh:.1f} kWh",
            "deficit": f"{deficit_to_charge_kwh:.1f} kWh",
            "pv": f"{pv_forecast_kwh:.1f} kWh",
            "heat_pump": f"{heat_pump_kwh:.1f} kWh",
            "current": f"{charge_current:.0f} A",
            "window": f"{start_hour:02d}:00-{end_hour:02d}:00",
        },
        full_details={
            "target_soc": round(target_soc, 1),
            "current_soc": round(current_soc, 1),
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "deficit_kwh": round(deficit_to_charge_kwh, 2),
            "deficit_raw_kwh": round(deficit_raw_kwh, 2),
            "losses_kwh": round(losses_kwh, 2),
            "pv_forecast_kwh": round(pv_forecast_kwh, 2),
            "heat_pump_kwh": round(heat_pump_kwh, 2),
            "charge_current_a": round(charge_current, 1),
            "efficiency": round(efficiency, 1),
            "margin": margin,
            "start_hour": start_hour,
            "end_hour": end_hour,
        },
    )
