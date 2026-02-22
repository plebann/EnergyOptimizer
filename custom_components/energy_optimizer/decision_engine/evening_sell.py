"""Evening peak sell decision logic."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import Context
from homeassistant.util import dt as dt_util

from ..calculations.battery import calculate_battery_reserve, kwh_to_soc
from ..calculations.energy import calculate_export_power, calculate_losses, calculate_surplus_energy
from ..calculations.utils import build_hourly_usage_array
from ..const import (
    CONF_EVENING_MAX_PRICE_SENSOR,
    CONF_EXPORT_POWER_ENTITY,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_PV_PRODUCTION_SENSOR,
    CONF_WORK_MODE_ENTITY,
)
from ..controllers.inverter import set_export_power, set_program_soc, set_work_mode
from ..decision_engine.common import (
    build_evening_sell_outcome,
    get_battery_config,
    get_required_current_soc_state,
    get_required_prog5_soc_state,
    resolve_entry,
)
from ..helpers import (
    get_float_state_info,
    get_required_float_state,
    is_test_sell_mode,
    resolve_tariff_start_hour,
)
from ..utils.forecast import get_heat_pump_forecast_window, get_pv_forecast_window
from ..utils.logging import DecisionOutcome, log_decision_unified
from ..utils.time_window import build_hour_window

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _build_no_action_outcome(
    *,
    reason: str,
    current_soc: float,
    evening_price: float | None,
    threshold_price: float | None,
) -> DecisionOutcome:
    """Build no-action outcome for evening sell routine."""
    summary = "No evening peak sell action"
    key_metrics: dict[str, str] = {
        "result": summary,
        "current_soc": f"{current_soc:.0f}%",
    }
    if evening_price is not None:
        key_metrics["evening_price"] = f"{evening_price:.1f} PLN/MWh"
    if threshold_price is not None:
        key_metrics["threshold_price"] = f"{threshold_price:.1f} PLN/MWh"

    return DecisionOutcome(
        scenario="Evening Peak Sell",
        action_type="no_action",
        summary=summary,
        reason=reason,
        key_metrics=key_metrics,
        full_details={
            "current_soc": round(current_soc, 1),
            "evening_price": round(evening_price, 2) if evening_price is not None else None,
            "threshold_price": (
                round(threshold_price, 2) if threshold_price is not None else None
            ),
            "reason": reason,
        },
    )


async def async_run_evening_sell(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    margin: float | None = None,
) -> None:
    """Run evening peak sell routine."""
    integration_context = Context()

    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    config = entry.data

    current_soc_state = get_required_current_soc_state(hass, config)
    if current_soc_state is None:
        return
    _, current_soc = current_soc_state

    prog5_soc_state = get_required_prog5_soc_state(hass, config)
    if prog5_soc_state is None:
        return
    prog5_soc_entity, _ = prog5_soc_state

    evening_price = get_required_float_state(
        hass,
        config.get(CONF_EVENING_MAX_PRICE_SENSOR),
        entity_name="Evening max price sensor",
    )
    threshold_price = float(config.get(CONF_MIN_ARBITRAGE_PRICE, 0.0) or 0.0)

    if evening_price is None:
        outcome = _build_no_action_outcome(
            reason="Missing evening max price",
            current_soc=current_soc,
            evening_price=evening_price,
            threshold_price=threshold_price,
        )
        await log_decision_unified(
            hass, entry, outcome, context=integration_context, logger=_LOGGER
        )
        return

    if evening_price <= threshold_price:
        outcome = _build_no_action_outcome(
            reason="Evening price is not above minimum arbitrage price",
            current_soc=current_soc,
            evening_price=evening_price,
            threshold_price=threshold_price,
        )
        outcome.full_details["min_arbitrage_price"] = round(threshold_price, 2)
        outcome.key_metrics["min_arbitrage_price"] = f"{threshold_price:.1f} PLN/MWh"
        await log_decision_unified(
            hass, entry, outcome, context=integration_context, logger=_LOGGER
        )
        return

    margin = margin if margin is not None else 1.1
    bc = get_battery_config(config)

    now_hour = dt_util.as_local(dt_util.utcnow()).hour
    start_hour = (now_hour + 1) % 24
    end_hour = resolve_tariff_start_hour(hass, config, default_hour=22)

    hours_window = build_hour_window(start_hour, end_hour)
    hours = max(len(hours_window), 1)

    hourly_usage = build_hourly_usage_array(
        config,
        hass.states.get,
        daily_load_fallback=None,
    )
    usage_kwh = sum(hourly_usage[hour] for hour in hours_window)

    heat_pump_kwh, _ = await get_heat_pump_forecast_window(
        hass, config, start_hour=start_hour, end_hour=end_hour
    )
    pv_forecast_kwh, _ = get_pv_forecast_window(
        hass,
        config,
        start_hour=start_hour,
        end_hour=end_hour,
        apply_efficiency=False,
        compensate=True,
        entry_id=entry.entry_id,
    )

    _, losses_kwh = calculate_losses(
        hass,
        config,
        hours=hours,
        margin=margin,
    )

    required_kwh = (usage_kwh + heat_pump_kwh + losses_kwh) * margin
    reserve_kwh = calculate_battery_reserve(
        current_soc,
        bc.min_soc,
        bc.capacity_ah,
        bc.voltage,
        efficiency=bc.efficiency,
    )
    surplus_kwh = calculate_surplus_energy(
        reserve_kwh,
        required_kwh,
        pv_forecast_kwh,
    )

    if surplus_kwh <= 0.0:
        outcome = _build_no_action_outcome(
            reason="No surplus energy available for selling",
            current_soc=current_soc,
            evening_price=evening_price,
            threshold_price=threshold_price,
        )
        await log_decision_unified(
            hass, entry, outcome, context=integration_context, logger=_LOGGER
        )
        return

    pv_production_entity = config.get(CONF_PV_PRODUCTION_SENSOR)
    pv_today_kwh: float | None = None
    if pv_production_entity:
        pv_value, _pv_raw, pv_error = get_float_state_info(hass, str(pv_production_entity))
        if pv_error is None and pv_value is not None and pv_value >= 0.0:
            pv_today_kwh = pv_value

    if pv_today_kwh is not None and surplus_kwh > pv_today_kwh:
        _LOGGER.info(
            "Clamping surplus from %.2f kWh to today's PV production %.2f kWh",
            surplus_kwh,
            pv_today_kwh,
        )
        surplus_kwh = pv_today_kwh

    target_soc = max(
        current_soc - kwh_to_soc(surplus_kwh, bc.capacity_ah, bc.voltage),
        bc.min_soc,
    )
    if target_soc >= current_soc:
        outcome = _build_no_action_outcome(
            reason="Calculated target SOC does not require discharge",
            current_soc=current_soc,
            evening_price=evening_price,
            threshold_price=threshold_price,
        )
        await log_decision_unified(
            hass, entry, outcome, context=integration_context, logger=_LOGGER
        )
        return

    export_power_w = calculate_export_power(surplus_kwh)

    work_mode_entity = config.get(CONF_WORK_MODE_ENTITY)
    export_power_entity = config.get(CONF_EXPORT_POWER_ENTITY)
    sell_test_mode = is_test_sell_mode(hass, entry)

    if sell_test_mode:
        _LOGGER.info(
            "Test sell mode enabled - skipping evening sell inverter writes"
        )
    else:
        await set_work_mode(
            hass,
            str(work_mode_entity) if work_mode_entity else None,
            "Export First",
            entry=entry,
            logger=_LOGGER,
            context=integration_context,
        )
        await set_program_soc(
            hass,
            prog5_soc_entity,
            target_soc,
            entry=entry,
            logger=_LOGGER,
            context=integration_context,
        )
        await set_export_power(
            hass,
            str(export_power_entity) if export_power_entity else None,
            export_power_w,
            entry=entry,
            logger=_LOGGER,
            context=integration_context,
        )

    outcome = build_evening_sell_outcome(
        target_soc=target_soc,
        current_soc=current_soc,
        surplus_kwh=surplus_kwh,
        reserve_kwh=reserve_kwh,
        required_kwh=required_kwh,
        pv_forecast_kwh=pv_forecast_kwh,
        heat_pump_kwh=heat_pump_kwh,
        losses_kwh=losses_kwh,
        start_hour=start_hour,
        end_hour=end_hour,
        export_power_w=export_power_w,
        evening_price=evening_price,
        threshold_price=threshold_price,
    )
    outcome.full_details["test_sell_mode"] = sell_test_mode
    if not sell_test_mode:
        outcome.entities_changed = [
            {"entity_id": prog5_soc_entity, "value": target_soc},
        ]
        if work_mode_entity:
            outcome.entities_changed.append(
                {"entity_id": str(work_mode_entity), "option": "Export First"}
            )
        if export_power_entity:
            outcome.entities_changed.append(
                {"entity_id": str(export_power_entity), "value": export_power_w}
            )

    await log_decision_unified(
        hass,
        entry,
        outcome,
        context=integration_context,
        logger=_LOGGER,
    )