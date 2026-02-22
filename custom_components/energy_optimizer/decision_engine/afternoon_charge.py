"""Afternoon grid charge decision logic."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import Context
from homeassistant.util import dt as dt_util

from ..calculations.battery import (
    apply_efficiency_compensation,
    calculate_battery_reserve,
    calculate_charge_current,
    calculate_soc_delta,
    calculate_target_soc,
    soc_to_kwh,
)
from ..calculations.energy import calculate_losses, hourly_demand
from ..calculations.energy import calculate_needed_reserve
from ..calculations.utils import build_hourly_usage_array
from ..const import (
    CONF_CHARGE_CURRENT_ENTITY,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_PV_FORECAST_REMAINING,
    CONF_PV_FORECAST_TODAY,
    CONF_PV_PRODUCTION_SENSOR,
    CONF_SELL_WINDOW_PRICE_SENSOR,
)
from ..decision_engine.common import (
    build_afternoon_charge_outcome,
    calculate_target_soc_from_needed_reserve,
    get_battery_config,
    get_entry_data,
    get_required_current_soc_state,
    get_required_prog4_soc_state,
    handle_no_action_soc_update,
    resolve_entry,
)
from ..helpers import (
    get_required_float_state,
    resolve_sell_window_start_hour,
    resolve_tariff_start_hour,
)
from ..controllers.inverter import set_charge_current, set_program_soc
from ..utils.forecast import get_heat_pump_forecast_window, get_pv_forecast_window
from ..utils.pv_forecast import get_forecast_adjusted_kwh, get_pv_compensation_factor
from ..utils.logging import DecisionOutcome, log_decision_unified

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_run_afternoon_charge(
    hass: HomeAssistant, *, entry_id: str | None = None, margin: float | None = None
) -> None:
    """Run afternoon grid charge routine."""

    # Create integration context for this decision engine run
    integration_context = Context()

    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    config = entry.data

    entry_data = get_entry_data(hass, entry.entry_id)
    grid_assist_sensor = (
        entry_data.get("afternoon_grid_assist_sensor")
        if entry_data is not None
        else None
    )

    def _set_grid_assist(enabled: bool) -> None:
        if grid_assist_sensor is not None:
            grid_assist_sensor.set_assist(enabled)

    prog4_soc_state = get_required_prog4_soc_state(hass, config)
    if prog4_soc_state is None:
        return
    prog4_soc_entity, prog4_soc_value = prog4_soc_state

    current_soc_state = get_required_current_soc_state(hass, config)
    if current_soc_state is None:
        return
    _, current_soc = current_soc_state

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

    start_hour = resolve_tariff_start_hour(hass, config)
    end_hour = 22
    hours = max(end_hour - start_hour, 1)

    usage_kwh = sum(hourly_usage[hour] for hour in range(start_hour, end_hour))
    
    heat_pump_kwh, heat_pump_hourly = await get_heat_pump_forecast_window(
        hass, config, start_hour=start_hour, end_hour=end_hour
    )
    pv_forecast_kwh, pv_forecast_hourly = get_pv_forecast_window(
        hass,
        config,
        start_hour=start_hour,
        end_hour=end_hour,
        apply_efficiency=False,
        compensate=True,
        entry_id=entry.entry_id,
    )

    losses_hourly, losses_kwh = calculate_losses(
        hass, config, hours=hours, margin=margin
    )

    required_kwh = (usage_kwh + heat_pump_kwh + losses_kwh) * margin

    if required_kwh <= 0.0:
        _LOGGER.info(
            "Required afternoon energy is zero or negative, proceeding with arbitrage only"
        )
        required_kwh = 0.0

    pv_compensation_factor = get_pv_compensation_factor(hass, entry.entry_id)

    needed_reserve_kwh = calculate_needed_reserve(required_kwh, pv_forecast_kwh)
    gap_kwh = needed_reserve_kwh - reserve_kwh

    arbitrage_kwh, arbitrage_details = _calculate_arbitrage_kwh(
        hass,
        config,
        start_hour=start_hour,
        end_hour=end_hour,
        sell_start_hour=resolve_sell_window_start_hour(hass, config),
        current_soc=current_soc,
        capacity_ah=bc.capacity_ah,
        voltage=bc.voltage,
        required_kwh=required_kwh,
        pv_forecast_hourly=pv_forecast_hourly,
        heat_pump_hourly=heat_pump_hourly,
        losses_hourly=losses_hourly,
        hourly_usage=hourly_usage,
        margin=margin,
        min_arbitrage_price=config.get(CONF_MIN_ARBITRAGE_PRICE, 0.0),
        sell_price_entity=config.get(CONF_SELL_WINDOW_PRICE_SENSOR),
        pv_forecast_today_entity=config.get(CONF_PV_FORECAST_TODAY),
        pv_forecast_remaining_entity=config.get(CONF_PV_FORECAST_REMAINING),
        pv_production_entity=config.get(CONF_PV_PRODUCTION_SENSOR),
        entry_id=entry.entry_id,
    )

    base_gap_kwh = max(gap_kwh, 0.0)
    total_gap_kwh = base_gap_kwh + arbitrage_kwh

    _set_grid_assist(base_gap_kwh > 0.0)

    if total_gap_kwh <= 0.0:
        target_soc = calculate_target_soc_from_needed_reserve(
            needed_reserve_kwh=needed_reserve_kwh,
            min_soc=bc.min_soc,
            max_soc=bc.max_soc,
            capacity_ah=bc.capacity_ah,
            voltage=bc.voltage,
        )
        await _handle_no_action(
            hass,
            entry,
            integration_context=integration_context,
            prog4_soc_entity=prog4_soc_entity,
            prog4_soc_value=prog4_soc_value,
            target_soc=target_soc,
            reserve_kwh=reserve_kwh,
            required_kwh=required_kwh,
            needed_reserve_kwh=needed_reserve_kwh,
            gap_kwh=total_gap_kwh,
            pv_forecast_kwh=pv_forecast_kwh,
            heat_pump_kwh=heat_pump_kwh,
            losses_kwh=losses_kwh,
            start_hour=start_hour,
            end_hour=end_hour,
            arbitrage_details=arbitrage_details,
            usage_kwh=usage_kwh,
            pv_compensation_factor=pv_compensation_factor,
        )
        return

    gap_to_charge_kwh = apply_efficiency_compensation(
        total_gap_kwh,
        bc.efficiency,
    )
    soc_delta = calculate_soc_delta(
        gap_to_charge_kwh,
        capacity_ah=bc.capacity_ah,
        voltage=bc.voltage,
    )
    target_soc = calculate_target_soc(current_soc, soc_delta, max_soc=bc.max_soc)

    charge_current_entity = config.get(CONF_CHARGE_CURRENT_ENTITY)
    charge_current = calculate_charge_current(
        gap_to_charge_kwh,
        current_soc=current_soc,
        capacity_ah=bc.capacity_ah,
        voltage=bc.voltage,
    )

    await set_program_soc(
        hass,
        prog4_soc_entity,
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

    outcome = build_afternoon_charge_outcome(
        scenario="Afternoon Grid Charge",
        target_soc=target_soc,
        required_kwh=required_kwh,
        needed_reserve_kwh=needed_reserve_kwh,
        reserve_kwh=reserve_kwh,
        gap_to_charge_kwh=gap_to_charge_kwh,
        gap_all_kwh=gap_kwh,
        arbitrage_kwh=arbitrage_kwh,
        arbitrage_details=arbitrage_details,
        pv_forecast_kwh=pv_forecast_kwh,
        heat_pump_kwh=heat_pump_kwh,
        charge_current=charge_current,
        current_soc=current_soc,
        losses_kwh=losses_kwh,
        efficiency=bc.efficiency,
        margin=margin,
        start_hour=start_hour,
        end_hour=end_hour,
        usage_kwh=usage_kwh,
        pv_compensation_factor=pv_compensation_factor,
    )
    outcome.entities_changed = [
        {"entity_id": prog4_soc_entity, "value": target_soc},
        {"entity_id": charge_current_entity, "value": charge_current},
    ]
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )


def _build_no_action_outcome(
    *,
    reserve_kwh: float,
    required_kwh: float,
    needed_reserve_kwh: float,
    pv_forecast_kwh: float,
    heat_pump_kwh: float,
    gap_kwh: float,
    losses_kwh: float,
    start_hour: int,
    end_hour: int,
    usage_kwh: float,
    pv_compensation_factor: float | None,
    arbitrage_details: dict[str, float | str] | None = None,
) -> DecisionOutcome:
    summary = "No action needed"
    return DecisionOutcome(
        scenario="Afternoon Grid Charge",
        action_type="no_action",
        summary=summary,
        reason=(
            f"Gap {gap_kwh:.1f} kWh, reserve {reserve_kwh:.1f} kWh, "
            f"required {required_kwh:.1f} kWh, PV {pv_forecast_kwh:.1f} kWh"
        ),
        key_metrics={
            "result": summary,
            "reserve": f"{reserve_kwh:.1f} kWh",
            "required": f"{required_kwh:.1f} kWh",
            "needed_reserve": f"{needed_reserve_kwh:.1f} kWh",
            "pv": f"{pv_forecast_kwh:.1f} kWh",
            "heat_pump": f"{heat_pump_kwh:.1f} kWh",
            "window": f"{start_hour:02d}:00-{end_hour:02d}:00",
        },
        full_details={
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "needed_reserve_kwh": round(needed_reserve_kwh, 2),
            "gap_kwh": round(gap_kwh, 2),
            "usage_kwh": round(usage_kwh, 2),
            "pv_forecast_kwh": round(pv_forecast_kwh, 2),
            "pv_compensation_factor": (
                round(pv_compensation_factor, 4)
                if pv_compensation_factor is not None
                else None
            ),
            "heat_pump_kwh": round(heat_pump_kwh, 2),
            "losses_kwh": round(losses_kwh, 2),
            "start_hour": start_hour,
            "end_hour": end_hour,
            **(arbitrage_details or {}),
        },
    )


async def _handle_no_action(
    hass: HomeAssistant,
    entry,
    *,
    integration_context: Context,
    prog4_soc_entity: str,
    prog4_soc_value: float,
    target_soc: float,
    reserve_kwh: float,
    required_kwh: float,
    needed_reserve_kwh: float,
    gap_kwh: float,
    pv_forecast_kwh: float,
    heat_pump_kwh: float,
    losses_kwh: float,
    start_hour: int,
    end_hour: int,
    usage_kwh: float,
    pv_compensation_factor: float | None,
    arbitrage_details: dict[str, float | str] | None = None,
) -> None:
    """Handle no-action path."""
    outcome = _build_no_action_outcome(
        reserve_kwh=reserve_kwh,
        required_kwh=required_kwh,
        needed_reserve_kwh=needed_reserve_kwh,
        pv_forecast_kwh=pv_forecast_kwh,
        gap_kwh=gap_kwh,
        heat_pump_kwh=heat_pump_kwh,
        losses_kwh=losses_kwh,
        start_hour=start_hour,
        end_hour=end_hour,
        usage_kwh=usage_kwh,
        pv_compensation_factor=pv_compensation_factor,
        arbitrage_details=arbitrage_details,
    )
    await handle_no_action_soc_update(
        hass,
        entry,
        integration_context=integration_context,
        prog_soc_entity=prog4_soc_entity,
        current_prog_soc=prog4_soc_value,
        target_soc=target_soc,
        outcome=outcome,
    )




def _calculate_arbitrage_kwh(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    start_hour: int,
    end_hour: int,
    sell_start_hour: int,
    current_soc: float,
    capacity_ah: float,
    voltage: float,
    required_kwh: float,
    pv_forecast_hourly: dict[int, float],
    heat_pump_hourly: dict[int, float],
    losses_hourly: dict[int, float],
    hourly_usage: dict[int, float],
    margin: float,
    min_arbitrage_price: float,
    sell_price_entity: str | None,
    pv_forecast_today_entity: str | None,
    pv_forecast_remaining_entity: str | None,
    pv_production_entity: str | None,
    entry_id: str | None = None,
) -> tuple[float, dict[str, float | str]]:
    details: dict[str, float | str] = {
        "arbitrage_reason": "not_applicable",
    }

    sell_price = get_required_float_state(
        hass, sell_price_entity, entity_name="Sell window price"
    )
    if sell_price is None:
        details["arbitrage_reason"] = "missing_sell_price"
        return 0.0, details

    details["sell_price"] = round(sell_price, 4)
    details["min_arbitrage_price"] = round(float(min_arbitrage_price or 0.0), 4)
    if sell_price <= float(min_arbitrage_price or 0.0):
        details["arbitrage_reason"] = "sell_price_below_threshold"
        return 0.0, details

    forecast_adjusted, forecast_reason = get_forecast_adjusted_kwh(
        hass,
        config,
        pv_forecast_today_entity=pv_forecast_today_entity,
        pv_forecast_remaining_entity=pv_forecast_remaining_entity,
        pv_production_entity=pv_production_entity,
        entry_id=entry_id,
    )
    if forecast_adjusted is None:
        details["arbitrage_reason"] = forecast_reason or "invalid_forecast_adjustment"
        return 0.0, details

    capacity_kwh = soc_to_kwh(100.0, capacity_ah, voltage)
    current_energy_kwh = soc_to_kwh(current_soc, capacity_ah, voltage)
    free_after = capacity_kwh - (current_energy_kwh + required_kwh)

    now_hour = dt_util.as_local(dt_util.utcnow()).hour
    surplus_start = max(start_hour, now_hour)
    surplus_end = min(sell_start_hour, end_hour)
    if surplus_end <= surplus_start:
        surplus_kwh = 0.0
    else:
        surplus_kwh = sum(
            max(
                pv_forecast_hourly.get(hour, 0.0)
                - hourly_demand(
                    hour,
                    hourly_usage=hourly_usage,
                    heat_pump_hourly=heat_pump_hourly,
                    losses_hourly=losses_hourly,
                    margin=margin,
                ),
                0.0,
            )
            for hour in range(surplus_start, surplus_end)
        )

    arb_limit = max(free_after - surplus_kwh, 0.0)
    arbitrage_kwh = min(arb_limit, forecast_adjusted)

    details.update(
        {
            "forecast_adjusted": round(forecast_adjusted, 2),
            "surplus_kwh": round(surplus_kwh, 2),
            "free_after_kwh": round(free_after, 2),
            "arb_limit_kwh": round(arb_limit, 2),
            "sell_window_start_hour": int(sell_start_hour),
        }
    )

    if arbitrage_kwh <= 0:
        details["arbitrage_reason"] = "arb_limit_zero"
        return 0.0, details

    details["arbitrage_reason"] = "enabled"
    return arbitrage_kwh, details
