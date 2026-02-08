"""Morning grid charge decision logic."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..calculations.battery import (
    calculate_battery_reserve,
    calculate_charge_current,
    calculate_soc_delta,
    calculate_target_soc,
)
from ..calculations.energy import calculate_losses, calculate_sufficiency_window
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
from ..helpers import (
    is_balancing_ongoing,
    resolve_tariff_end_hour,
    set_balancing_ongoing,
)
from ..controllers.inverter import set_charge_current, set_program_soc
from ..utils.forecast import async_get_forecasts
from ..utils.logging import DecisionOutcome, format_sufficiency_hour, log_decision_unified

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

    prog2_soc_state = get_required_prog2_soc_state(hass, config)
    if prog2_soc_state is None:
        return
    prog2_soc_entity, prog2_soc_value = prog2_soc_state

    current_soc_state = get_required_current_soc_state(hass, config)
    if current_soc_state is None:
        return
    _battery_soc_entity, current_soc = current_soc_state

    if await _handle_balancing_ongoing(
        hass, entry, integration_context=integration_context
    ):
        return

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

    tariff_end_hour = resolve_tariff_end_hour(hass, config)

    start_hour = 6
    hours_morning = max(tariff_end_hour - start_hour, 1)
    heat_pump_kwh, heat_pump_hourly, pv_forecast_kwh, pv_forecast_hourly = (
        await async_get_forecasts(
            hass,
            config,
            start_hour=start_hour,
            end_hour=tariff_end_hour,
        )
    )
    losses_hourly, losses_kwh = calculate_losses(
        hass, config, hours_morning=hours_morning, margin=margin
    )
    (
        required_kwh,
        required_sufficiency_kwh,
        pv_sufficiency_kwh,
        sufficiency_hour,
        sufficiency_reached,
    ) = calculate_sufficiency_window(
        start_hour=start_hour,
        end_hour=tariff_end_hour,
        hourly_usage=hourly_usage,
        heat_pump_hourly=heat_pump_hourly,
        losses_hourly=losses_hourly,
        margin=margin,
        pv_forecast_hourly=pv_forecast_hourly,
    )

    if required_kwh <= 0.0:
        _LOGGER.info("Required morning energy is zero or negative, skipping")
        return

    deficit_full_kwh = required_kwh - reserve_kwh - pv_forecast_kwh
    deficit_sufficiency_kwh = (
        required_sufficiency_kwh - reserve_kwh - pv_sufficiency_kwh
    )
    deficit_kwh = max(deficit_full_kwh, deficit_sufficiency_kwh)

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
            required_sufficiency_kwh=required_sufficiency_kwh,
            pv_forecast_kwh=pv_forecast_kwh,
            pv_sufficiency_kwh=pv_sufficiency_kwh,
            heat_pump_kwh=heat_pump_kwh,
            deficit_full_kwh=deficit_full_kwh,
            deficit_sufficiency_kwh=deficit_sufficiency_kwh,
            sufficiency_hour=sufficiency_hour,
            sufficiency_reached=sufficiency_reached,
        )
        return

    deficit_to_charge_kwh = (
        deficit_kwh / ((efficiency / 100.0) ** 2) if efficiency else deficit_kwh
    )
    soc_delta = calculate_soc_delta(
        deficit_to_charge_kwh, capacity_ah=capacity_ah, voltage=voltage
    )
    target_soc = calculate_target_soc(
        current_soc, soc_delta, max_soc=max_soc
    )

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
        required_sufficiency_kwh=required_sufficiency_kwh,
        reserve_kwh=reserve_kwh,
        deficit_to_charge_kwh=deficit_to_charge_kwh,
        deficit_raw_kwh=deficit_kwh,
        deficit_full_kwh=deficit_full_kwh,
        deficit_sufficiency_kwh=deficit_sufficiency_kwh,
        pv_forecast_kwh=pv_forecast_kwh,
        pv_sufficiency_kwh=pv_sufficiency_kwh,
        heat_pump_kwh=heat_pump_kwh,
        charge_current=charge_current,
        current_soc=current_soc,
        losses_kwh=losses_kwh,
        efficiency=efficiency,
        margin=margin,
        sufficiency_hour=sufficiency_hour,
        sufficiency_reached=sufficiency_reached,
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
    required_sufficiency_kwh: float,
    pv_forecast_kwh: float,
    pv_sufficiency_kwh: float,
    heat_pump_kwh: float,
    deficit_full_kwh: float,
    deficit_sufficiency_kwh: float,
    sufficiency_hour: int,
    sufficiency_reached: bool,
) -> DecisionOutcome:
    sufficiency_label = format_sufficiency_hour(
        sufficiency_hour, sufficiency_reached=sufficiency_reached
    )
    summary = "No action needed"
    return DecisionOutcome(
        scenario="Morning Grid Charge",
        action_type="no_action",
        summary=summary,
        reason=(
            f"Deficit full {deficit_full_kwh:.1f} kWh, "
            f"deficit sufficiency {deficit_sufficiency_kwh:.1f} kWh"
        ),
        key_metrics={
            "result": summary,
            "reserve": f"{reserve_kwh:.1f} kWh",
            "required": f"{required_kwh:.1f} kWh",
            "required_sufficiency": f"{required_sufficiency_kwh:.1f} kWh",
            "pv": f"{pv_forecast_kwh:.1f} kWh",
            "pv_sufficiency": f"{pv_sufficiency_kwh:.1f} kWh",
            "heat_pump": f"{heat_pump_kwh:.1f} kWh",
            "sufficiency_hour": sufficiency_label,
        },
        full_details={
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "required_sufficiency_kwh": round(required_sufficiency_kwh, 2),
            "pv_sufficiency_kwh": round(pv_sufficiency_kwh, 2),
            "pv_forecast_kwh": round(pv_forecast_kwh, 2),
            "heat_pump_kwh": round(heat_pump_kwh, 2),
            "deficit_full_kwh": round(deficit_full_kwh, 2),
            "deficit_sufficiency_kwh": round(deficit_sufficiency_kwh, 2),
            "sufficiency_hour": sufficiency_hour,
            "sufficiency_reached": sufficiency_reached,
        },
    )


def _build_balancing_ongoing_outcome() -> DecisionOutcome:
    """Build outcome for balancing ongoing skip."""
    summary = "Battery balancing ongoing"
    return DecisionOutcome(
        scenario="Morning Grid Charge",
        action_type="no_action",
        summary=summary,
        reason="Battery balancing in progress",
        key_metrics={
            "result": summary,
            "balancing": "ongoing",
        },
        full_details={
            "balancing_ongoing": True,
        },
    )


async def _handle_balancing_ongoing(
    hass: HomeAssistant,
    entry,
    *,
    integration_context: Context,
) -> bool:
    """Handle early exit when balancing is ongoing."""
    if not is_balancing_ongoing(hass, entry.entry_id):
        return False

    set_balancing_ongoing(hass, entry.entry_id, ongoing=False)
    outcome = _build_balancing_ongoing_outcome()
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )
    return True


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
    required_sufficiency_kwh: float,
    pv_forecast_kwh: float,
    pv_sufficiency_kwh: float,
    heat_pump_kwh: float,
    deficit_full_kwh: float,
    deficit_sufficiency_kwh: float,
    sufficiency_hour: int,
    sufficiency_reached: bool,
) -> None:
    """Handle no-action path."""
    outcome = _build_no_action_outcome(
        reserve_kwh=reserve_kwh,
        required_kwh=required_kwh,
        required_sufficiency_kwh=required_sufficiency_kwh,
        pv_forecast_kwh=pv_forecast_kwh,
        pv_sufficiency_kwh=pv_sufficiency_kwh,
        heat_pump_kwh=heat_pump_kwh,
        deficit_full_kwh=deficit_full_kwh,
        deficit_sufficiency_kwh=deficit_sufficiency_kwh,
        sufficiency_hour=sufficiency_hour,
        sufficiency_reached=sufficiency_reached,
    )
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )

def _build_charge_outcome(
    *,
    target_soc: float,
    required_kwh: float,
    required_sufficiency_kwh: float,
    reserve_kwh: float,
    deficit_to_charge_kwh: float,
    deficit_raw_kwh: float,
    deficit_full_kwh: float,
    deficit_sufficiency_kwh: float,
    pv_forecast_kwh: float,
    pv_sufficiency_kwh: float,
    heat_pump_kwh: float,
    charge_current: float,
    current_soc: float,
    losses_kwh: float,
    efficiency: float,
    margin: float,
    sufficiency_hour: int,
    sufficiency_reached: bool,
) -> DecisionOutcome:
    summary = f"Battery scheduled to charge to {target_soc:.0f}%"
    return DecisionOutcome(
        scenario="Morning Grid Charge",
        action_type="charge_scheduled",
        summary=summary,
        reason=(
            f"Deficit {deficit_to_charge_kwh:.1f} kWh, reserve {reserve_kwh:.1f} kWh, "
            f"required {required_kwh:.1f} kWh, PV {pv_forecast_kwh:.1f} kWh, "
            f"current {charge_current:.0f} A"
        ),
        key_metrics={
            "result": summary,
            "target": f"{target_soc:.0f}%",
            "required": f"{required_kwh:.1f} kWh",
            "required_sufficiency": f"{required_sufficiency_kwh:.1f} kWh",
            "reserve": f"{reserve_kwh:.1f} kWh",
            "deficit": f"{deficit_to_charge_kwh:.1f} kWh",
            "deficit_full": f"{deficit_full_kwh:.1f} kWh",
            "deficit_sufficiency": f"{deficit_sufficiency_kwh:.1f} kWh",
            "pv": f"{pv_forecast_kwh:.1f} kWh",
            "pv_sufficiency": f"{pv_sufficiency_kwh:.1f} kWh",
            "heat_pump": f"{heat_pump_kwh:.1f} kWh",
            "current": f"{charge_current:.0f} A",
            "sufficiency_hour": format_sufficiency_hour(
                sufficiency_hour, sufficiency_reached=sufficiency_reached
            ),
        },
        full_details={
            "target_soc": round(target_soc, 1),
            "current_soc": round(current_soc, 1),
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "required_sufficiency_kwh": round(required_sufficiency_kwh, 2),
            "pv_sufficiency_kwh": round(pv_sufficiency_kwh, 2),
            "deficit_kwh": round(deficit_to_charge_kwh, 2),
            "deficit_raw_kwh": round(deficit_raw_kwh, 2),
            "deficit_full_kwh": round(deficit_full_kwh, 2),
            "deficit_sufficiency_kwh": round(deficit_sufficiency_kwh, 2),
            "losses_kwh": round(losses_kwh, 2),
            "pv_forecast_kwh": round(pv_forecast_kwh, 2),
            "heat_pump_kwh": round(heat_pump_kwh, 2),
            "charge_current_a": round(charge_current, 1),
            "efficiency": round(efficiency, 1),
            "margin": margin,
            "sufficiency_hour": sufficiency_hour,
            "sufficiency_reached": sufficiency_reached,
        },
    )
