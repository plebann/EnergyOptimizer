"""Morning grid charge decision logic."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import Context

from ..calculations.battery import (
    apply_efficiency_compensation,
    calculate_battery_reserve,
    calculate_charge_current,
    calculate_soc_delta,
    calculate_target_soc,
)
from ..calculations.energy import (
    calculate_losses,
    calculate_needed_reserve,
    calculate_needed_reserve_sufficiency,
    calculate_sufficiency_window,
)
from ..calculations.utils import build_hourly_usage_array
from ..const import (
    CONF_CHARGE_CURRENT_ENTITY,
)
from ..decision_engine.common import (
    build_morning_charge_outcome,
    calculate_target_soc_from_needed_reserve,
    get_battery_config,
    get_required_current_soc_state,
    get_required_prog2_soc_state,
    handle_no_action_soc_update,
    resolve_entry,
)
from ..helpers import (
    is_balancing_ongoing,
    resolve_tariff_end_hour,
    set_balancing_ongoing,
)
from ..controllers.inverter import set_charge_current, set_program_soc
from ..utils.forecast import get_heat_pump_forecast_window, get_pv_forecast_window
from ..utils.pv_forecast import get_pv_compensation_factor
from ..utils.logging import DecisionOutcome, format_sufficiency_hour, log_decision_unified

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

async def async_run_morning_charge(
    hass: HomeAssistant, *, entry_id: str | None = None, margin: float | None = None
) -> None:
    """Run morning grid charge routine."""

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
    _, current_soc = current_soc_state

    if await _handle_balancing_ongoing(
        hass, entry, integration_context=integration_context
    ):
        return

    bc = get_battery_config(config)
    margin = margin if margin is not None else 1.1

    reserve_kwh = calculate_battery_reserve(
        current_soc,
        bc.min_soc,
        bc.capacity_ah,
        bc.voltage,
        efficiency=bc.efficiency,
    )

    hourly_usage = build_hourly_usage_array(
        config, hass.states.get, daily_load_fallback=None
    )

    tariff_end_hour = resolve_tariff_end_hour(hass, config)

    start_hour = 6
    hours = max(tariff_end_hour - start_hour, 1)
    heat_pump_kwh, heat_pump_hourly = await get_heat_pump_forecast_window(
        hass, config, start_hour=start_hour, end_hour=tariff_end_hour
    )
    pv_forecast_kwh, pv_forecast_hourly = get_pv_forecast_window(
        hass,
        config,
        start_hour=start_hour,
        end_hour=tariff_end_hour,
        compensate=True,
        entry_id=entry.entry_id,
    )
    losses_hourly, losses_kwh = calculate_losses(
        hass, config, hours=hours, margin=margin
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
        _LOGGER.info("Required morning energy is zero or negative")
        required_kwh = 0.0

    pv_compensation_factor = get_pv_compensation_factor(hass, entry.entry_id)

    needed_reserve_kwh = calculate_needed_reserve(required_kwh, pv_forecast_kwh)
    needed_reserve_sufficiency_kwh = calculate_needed_reserve_sufficiency(
        required_sufficiency_kwh, pv_sufficiency_kwh
    )
    needed_reserve_all_kwh = max(needed_reserve_kwh, needed_reserve_sufficiency_kwh)

    gap_kwh = needed_reserve_kwh - reserve_kwh
    gap_sufficiency_kwh = needed_reserve_sufficiency_kwh - reserve_kwh
    gap_all_kwh = max(gap_kwh, gap_sufficiency_kwh)

    if gap_all_kwh <= 0.0:
        target_soc = calculate_target_soc_from_needed_reserve(
            needed_reserve_kwh=needed_reserve_all_kwh,
            min_soc=bc.min_soc,
            max_soc=bc.max_soc,
            capacity_ah=bc.capacity_ah,
            voltage=bc.voltage,
        )
        await _handle_no_action(
            hass,
            entry,
            integration_context=integration_context,
            prog2_soc_entity=prog2_soc_entity,
            prog2_soc_value=prog2_soc_value,
            target_soc=target_soc,
            reserve_kwh=reserve_kwh,
            required_kwh=required_kwh,
            required_sufficiency_kwh=required_sufficiency_kwh,
            needed_reserve_kwh=needed_reserve_kwh,
            needed_reserve_sufficiency_kwh=needed_reserve_sufficiency_kwh,
            pv_forecast_kwh=pv_forecast_kwh,
            pv_sufficiency_kwh=pv_sufficiency_kwh,
            heat_pump_kwh=heat_pump_kwh,
            gap_kwh=gap_kwh,
            gap_sufficiency_kwh=gap_sufficiency_kwh,
            sufficiency_hour=sufficiency_hour,
            sufficiency_reached=sufficiency_reached,
            pv_compensation_factor=pv_compensation_factor,
        )
        return

    gap_to_charge_kwh = apply_efficiency_compensation(
        gap_all_kwh,
        bc.efficiency,
    )
    soc_delta = calculate_soc_delta(
        gap_to_charge_kwh,
        capacity_ah=bc.capacity_ah,
        voltage=bc.voltage,
    )
    target_soc = calculate_target_soc(
        current_soc, soc_delta, max_soc=bc.max_soc
    )

    charge_current_entity = config.get(CONF_CHARGE_CURRENT_ENTITY)
    charge_current = calculate_charge_current(
        gap_to_charge_kwh,
        current_soc=current_soc,
        capacity_ah=bc.capacity_ah,
        voltage=bc.voltage,
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

    outcome = build_morning_charge_outcome(
        scenario="Morning Grid Charge",
        target_soc=target_soc,
        required_kwh=required_kwh,
        required_sufficiency_kwh=required_sufficiency_kwh,
        needed_reserve_kwh=needed_reserve_kwh,
        needed_reserve_sufficiency_kwh=needed_reserve_sufficiency_kwh,
        reserve_kwh=reserve_kwh,
        gap_to_charge_kwh=gap_to_charge_kwh,
        gap_all_kwh=gap_all_kwh,
        gap_kwh=gap_kwh,
        gap_sufficiency_kwh=gap_sufficiency_kwh,
        pv_forecast_kwh=pv_forecast_kwh,
        pv_sufficiency_kwh=pv_sufficiency_kwh,
        heat_pump_kwh=heat_pump_kwh,
        charge_current=charge_current,
        current_soc=current_soc,
        losses_kwh=losses_kwh,
        efficiency=bc.efficiency,
        margin=margin,
        sufficiency_hour=sufficiency_hour,
        sufficiency_reached=sufficiency_reached,
        pv_compensation_factor=pv_compensation_factor,
        start_hour=start_hour,
        end_hour=tariff_end_hour,
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
    needed_reserve_kwh: float,
    needed_reserve_sufficiency_kwh: float,
    pv_forecast_kwh: float,
    pv_sufficiency_kwh: float,
    heat_pump_kwh: float,
    gap_kwh: float,
    gap_sufficiency_kwh: float,
    sufficiency_hour: int,
    sufficiency_reached: bool,
    pv_compensation_factor: float | None,
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
            f"Gap {gap_kwh:.1f} kWh, "
            f"gap sufficiency {gap_sufficiency_kwh:.1f} kWh"
        ),
        key_metrics={
            "result": summary,
            "reserve": f"{reserve_kwh:.1f} kWh",
            "required": f"{required_kwh:.1f} kWh",
            "needed_reserve": f"{needed_reserve_kwh:.1f} kWh",
            "needed_reserve_sufficiency": f"{needed_reserve_sufficiency_kwh:.1f} kWh",
            "required_sufficiency": f"{required_sufficiency_kwh:.1f} kWh",
            "pv": f"{pv_forecast_kwh:.1f} kWh",
            "pv_sufficiency": f"{pv_sufficiency_kwh:.1f} kWh",
            "heat_pump": f"{heat_pump_kwh:.1f} kWh",
            "sufficiency_hour": sufficiency_label,
        },
        full_details={
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "needed_reserve_kwh": round(needed_reserve_kwh, 2),
            "needed_reserve_sufficiency_kwh": round(needed_reserve_sufficiency_kwh, 2),
            "required_sufficiency_kwh": round(required_sufficiency_kwh, 2),
            "pv_sufficiency_kwh": round(pv_sufficiency_kwh, 2),
            "pv_forecast_kwh": round(pv_forecast_kwh, 2),
            "pv_compensation_factor": (
                round(pv_compensation_factor, 4)
                if pv_compensation_factor is not None
                else None
            ),
            "heat_pump_kwh": round(heat_pump_kwh, 2),
            "gap_kwh": round(gap_kwh, 2),
            "gap_sufficiency_kwh": round(gap_sufficiency_kwh, 2),
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
    target_soc: float,
    reserve_kwh: float,
    required_kwh: float,
    required_sufficiency_kwh: float,
    needed_reserve_kwh: float,
    needed_reserve_sufficiency_kwh: float,
    pv_forecast_kwh: float,
    pv_sufficiency_kwh: float,
    heat_pump_kwh: float,
    gap_kwh: float,
    gap_sufficiency_kwh: float,
    sufficiency_hour: int,
    sufficiency_reached: bool,
    pv_compensation_factor: float | None,
) -> None:
    """Handle no-action path."""
    outcome = _build_no_action_outcome(
        reserve_kwh=reserve_kwh,
        required_kwh=required_kwh,
        required_sufficiency_kwh=required_sufficiency_kwh,
        needed_reserve_kwh=needed_reserve_kwh,
        needed_reserve_sufficiency_kwh=needed_reserve_sufficiency_kwh,
        pv_forecast_kwh=pv_forecast_kwh,
        pv_sufficiency_kwh=pv_sufficiency_kwh,
        heat_pump_kwh=heat_pump_kwh,
        gap_kwh=gap_kwh,
        gap_sufficiency_kwh=gap_sufficiency_kwh,
        sufficiency_hour=sufficiency_hour,
        sufficiency_reached=sufficiency_reached,
        pv_compensation_factor=pv_compensation_factor,
    )
    await handle_no_action_soc_update(
        hass,
        entry,
        integration_context=integration_context,
        prog_soc_entity=prog2_soc_entity,
        current_prog_soc=prog2_soc_value,
        target_soc=target_soc,
        outcome=outcome,
    )



