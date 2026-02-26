"""Morning grid charge decision logic."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import Context

from ..calculations.battery import (
    calculate_battery_reserve,
)
from ..calculations.energy import (
    calculate_needed_reserve,
    calculate_needed_reserve_sufficiency,
)
from ..const import (
    CONF_CHARGE_CURRENT_ENTITY,
)
from ..decision_engine.common import (
    ChargeAction,
    EnergyBalance,
    ForecastData,
    SufficiencyResult,
    build_no_action_outcome,
    build_morning_charge_outcome,
    calculate_charge_action,
    calculate_target_soc_from_needed_reserve,
    compute_sufficiency,
    gather_forecasts,
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
from ..utils.pv_forecast import get_pv_compensation_factor
from ..utils.logging import DecisionOutcome, log_decision_unified

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

    tariff_end_hour = resolve_tariff_end_hour(hass, config)
    start_hour = 6

    forecasts = await gather_forecasts(
        hass,
        config,
        start_hour=start_hour,
        end_hour=tariff_end_hour,
        margin=margin,
        entry_id=entry.entry_id,
    )
    sufficiency = compute_sufficiency(forecasts)

    if sufficiency.required_kwh <= 0.0:
        _LOGGER.info("Required morning energy is zero or negative")
        sufficiency = SufficiencyResult(
            required_kwh=0.0,
            required_sufficiency_kwh=sufficiency.required_sufficiency_kwh,
            pv_sufficiency_kwh=sufficiency.pv_sufficiency_kwh,
            sufficiency_hour=sufficiency.sufficiency_hour,
            sufficiency_reached=sufficiency.sufficiency_reached,
        )

    pv_compensation_factor = get_pv_compensation_factor(hass, entry.entry_id)

    (
        balance,
        needed_reserve_sufficiency_kwh,
        gap_sufficiency_kwh,
        needed_reserve_all_kwh,
        base_gap_kwh,
    ) = _calculate_morning_balance(
        bc,
        current_soc=current_soc,
        forecasts=forecasts,
        sufficiency=sufficiency,
        pv_compensation_factor=pv_compensation_factor,
    )

    if balance.gap_kwh <= 0.0:
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
            current_soc=current_soc,
            target_soc=target_soc,
            forecasts=forecasts,
            sufficiency=sufficiency,
            balance=balance,
            base_gap_kwh=base_gap_kwh,
            needed_reserve_sufficiency_kwh=needed_reserve_sufficiency_kwh,
            gap_sufficiency_kwh=gap_sufficiency_kwh,
            pv_compensation_factor=pv_compensation_factor,
        )
        return

    action = calculate_charge_action(
        bc,
        gap_kwh=balance.gap_kwh,
        current_soc=current_soc,
    )

    charge_current_entity = config.get(CONF_CHARGE_CURRENT_ENTITY)

    await set_program_soc(
        hass,
        prog2_soc_entity,
        action.target_soc,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )
    await set_charge_current(
        hass,
        charge_current_entity,
        action.charge_current,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )

    outcome = build_morning_charge_outcome(
        scenario="Morning Grid Charge",
        action=action,
        balance=balance,
        forecasts=forecasts,
        sufficiency=sufficiency,
        needed_reserve_sufficiency_kwh=needed_reserve_sufficiency_kwh,
        gap_sufficiency_kwh=gap_sufficiency_kwh,
        current_soc=current_soc,
        efficiency=bc.efficiency,
        pv_compensation_factor=pv_compensation_factor,
    )
    outcome.entities_changed = [
        {"entity_id": prog2_soc_entity, "value": action.target_soc},
        {"entity_id": charge_current_entity, "value": action.charge_current},
    ]
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )


def _calculate_morning_balance(
    bc,
    *,
    current_soc: float,
    forecasts: ForecastData,
    sufficiency: SufficiencyResult,
    pv_compensation_factor: float | None,
) -> tuple[EnergyBalance, float, float, float, float]:
    """Calculate morning reserve/gap values."""
    reserve_kwh = calculate_battery_reserve(
        current_soc,
        bc.min_soc,
        bc.capacity_ah,
        bc.voltage,
        efficiency=bc.efficiency,
    )
    needed_reserve_kwh = calculate_needed_reserve(
        sufficiency.required_kwh,
        forecasts.pv_forecast_kwh,
    )
    needed_reserve_sufficiency_kwh = calculate_needed_reserve_sufficiency(
        sufficiency.required_sufficiency_kwh,
        sufficiency.pv_sufficiency_kwh,
    )
    needed_reserve_all_kwh = max(needed_reserve_kwh, needed_reserve_sufficiency_kwh)

    gap_kwh = needed_reserve_kwh - reserve_kwh
    gap_sufficiency_kwh = needed_reserve_sufficiency_kwh - reserve_kwh
    gap_all_kwh = max(gap_kwh, gap_sufficiency_kwh)

    return (
        EnergyBalance(
            reserve_kwh=reserve_kwh,
            required_kwh=sufficiency.required_kwh,
            needed_reserve_kwh=needed_reserve_kwh,
            gap_kwh=gap_all_kwh,
            pv_compensation_factor=pv_compensation_factor,
        ),
        needed_reserve_sufficiency_kwh,
        gap_sufficiency_kwh,
        needed_reserve_all_kwh,
        gap_kwh,
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
    current_soc: float,
    target_soc: float,
    forecasts: ForecastData,
    sufficiency: SufficiencyResult,
    balance: EnergyBalance,
    base_gap_kwh: float,
    needed_reserve_sufficiency_kwh: float,
    gap_sufficiency_kwh: float,
    pv_compensation_factor: float | None,
) -> None:
    """Handle no-action path."""
    outcome = build_no_action_outcome(
        scenario="Morning Grid Charge",
        reason=(
            f"Gap {base_gap_kwh:.1f} kWh, reserve {balance.reserve_kwh:.1f} kWh, "
            f"required {balance.required_kwh:.1f} kWh, PV {forecasts.pv_forecast_kwh:.1f} kWh, "
            f"gap sufficiency {gap_sufficiency_kwh:.1f} kWh"
        ),
        current_soc=current_soc,
        reserve_kwh=balance.reserve_kwh,
        required_kwh=balance.required_kwh,
        pv_forecast_kwh=forecasts.pv_forecast_kwh,
        sufficiency_hour=sufficiency.sufficiency_hour,
        sufficiency_reached=sufficiency.sufficiency_reached,
        key_metrics_extra={
            "needed_reserve": f"{balance.needed_reserve_kwh:.1f} kWh",
            "needed_reserve_sufficiency": f"{needed_reserve_sufficiency_kwh:.1f} kWh",
            "required_sufficiency": f"{sufficiency.required_sufficiency_kwh:.1f} kWh",
            "pv_sufficiency": f"{sufficiency.pv_sufficiency_kwh:.1f} kWh",
            "heat_pump": f"{forecasts.heat_pump_kwh:.1f} kWh",
        },
        full_details_extra={
            "needed_reserve_kwh": round(balance.needed_reserve_kwh, 2),
            "needed_reserve_sufficiency_kwh": round(needed_reserve_sufficiency_kwh, 2),
            "required_sufficiency_kwh": round(sufficiency.required_sufficiency_kwh, 2),
            "usage_kwh": round(forecasts.usage_kwh, 2),
            "pv_sufficiency_kwh": round(sufficiency.pv_sufficiency_kwh, 2),
            "pv_compensation_factor": (
                round(pv_compensation_factor, 4)
                if pv_compensation_factor is not None
                else None
            ),
            "heat_pump_kwh": round(forecasts.heat_pump_kwh, 2),
            "losses_kwh": round(forecasts.losses_kwh, 2),
            "gap_kwh": round(base_gap_kwh, 2),
            "gap_sufficiency_kwh": round(gap_sufficiency_kwh, 2),
        },
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



