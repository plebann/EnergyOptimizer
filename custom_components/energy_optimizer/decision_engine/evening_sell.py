"""Evening peak sell decision logic."""
from __future__ import annotations

from collections.abc import Callable
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import Context
from homeassistant.util import dt as dt_util

from ..calculations.battery import calculate_battery_reserve, kwh_to_soc
from ..calculations.energy import (
    calculate_export_power,
    calculate_losses,
    calculate_sufficiency_window,
    calculate_surplus_energy,
)
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
    build_surplus_sell_outcome,
    get_battery_config,
    get_required_current_soc_state,
    get_required_prog5_soc_state,
    resolve_entry,
)
from ..helpers import (
    get_float_state_info,
    get_required_float_state,
    is_test_sell_mode,
    resolve_tariff_end_hour,
    resolve_tariff_start_hour,
)
from ..utils.forecast import get_heat_pump_forecast_window, get_pv_forecast_window
from ..utils.logging import DecisionOutcome, format_sufficiency_hour, log_decision_unified
from ..utils.time_window import build_hour_window

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _build_no_action_outcome(
    *,
    reason: str,
    current_soc: float,
    evening_price: float | None = None,
    threshold_price: float | None = None,
    sufficiency_hour: int | None = None,
    sufficiency_reached: bool | None = None,
    surplus_kwh: float | None = None,
    total_needed_kwh: float | None = None,
) -> DecisionOutcome:
    """Build no-action outcome for evening sell routine."""
    summary = (
        "No surplus sell action"
        if sufficiency_hour is not None
        else "No evening peak sell action"
    )
    key_metrics: dict[str, str] = {
        "result": summary,
        "current_soc": f"{current_soc:.0f}%",
    }
    full_details: dict[str, Any] = {
        "current_soc": round(current_soc, 1),
        "evening_price": round(evening_price, 2) if evening_price is not None else None,
        "threshold_price": (
            round(threshold_price, 2) if threshold_price is not None else None
        ),
        "reason": reason,
    }

    if evening_price is not None:
        key_metrics["evening_price"] = f"{evening_price:.1f} PLN/MWh"
    if threshold_price is not None:
        key_metrics["threshold_price"] = f"{threshold_price:.1f} PLN/MWh"

    if sufficiency_hour is not None and sufficiency_reached is not None:
        key_metrics["sufficiency_hour"] = format_sufficiency_hour(
            sufficiency_hour,
            sufficiency_reached=sufficiency_reached,
        )
        full_details["sufficiency_hour"] = sufficiency_hour
        full_details["sufficiency_reached"] = sufficiency_reached

    if surplus_kwh is not None:
        key_metrics["surplus"] = f"{surplus_kwh:.1f} kWh"
        full_details["surplus_kwh"] = round(surplus_kwh, 2)

    if total_needed_kwh is not None:
        key_metrics["total_needed"] = f"{total_needed_kwh:.1f} kWh"
        full_details["total_needed_kwh"] = round(total_needed_kwh, 2)

    return DecisionOutcome(
        scenario="Evening Peak Sell",
        action_type="no_action",
        summary=summary,
        reason=reason,
        key_metrics=key_metrics,
        full_details=full_details,
    )


async def _execute_sell(
    hass: HomeAssistant,
    *,
    entry: ConfigEntry,
    config: dict[str, Any],
    bc: Any,
    current_soc: float,
    surplus_kwh: float,
    prog5_soc_entity: str,
    integration_context: Context,
    build_outcome_fn: Callable[[float, float, float], DecisionOutcome],
    build_no_action_fn: Callable[[float], DecisionOutcome],
) -> None:
    """Execute shared sell tail: clamp, target, writes, outcome and logging."""
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
        outcome = build_no_action_fn(surplus_kwh)
        await log_decision_unified(
            hass, entry, outcome, context=integration_context, logger=_LOGGER
        )
        return

    export_power_w = calculate_export_power(surplus_kwh)
    work_mode_entity = config.get(CONF_WORK_MODE_ENTITY)
    export_power_entity = config.get(CONF_EXPORT_POWER_ENTITY)
    sell_test_mode = is_test_sell_mode(hass, entry)

    if sell_test_mode:
        _LOGGER.info("Test sell mode enabled - skipping evening sell inverter writes")
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

    outcome = build_outcome_fn(target_soc, surplus_kwh, export_power_w)
    outcome.full_details["test_sell_mode"] = sell_test_mode
    if not sell_test_mode:
        outcome.entities_changed = [{"entity_id": prog5_soc_entity, "value": target_soc}]
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

    effective_margin = margin if margin is not None else 1.1

    if evening_price <= threshold_price:
        await _run_surplus_sell(
            hass,
            entry=entry,
            config=config,
            current_soc=current_soc,
            prog5_soc_entity=prog5_soc_entity,
            evening_price=evening_price,
            threshold_price=threshold_price,
            margin=effective_margin,
            integration_context=integration_context,
        )
        return

    await _run_high_price_sell(
        hass,
        entry=entry,
        config=config,
        current_soc=current_soc,
        prog5_soc_entity=prog5_soc_entity,
        evening_price=evening_price,
        threshold_price=threshold_price,
        margin=effective_margin,
        integration_context=integration_context,
    )


async def _run_high_price_sell(
    hass: HomeAssistant,
    *,
    entry: ConfigEntry,
    config: dict[str, Any],
    current_soc: float,
    prog5_soc_entity: str,
    evening_price: float,
    threshold_price: float,
    margin: float,
    integration_context: Context,
) -> None:
    """Run sell logic for high-price arbitrage branch."""
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

    def _make_outcome(target_soc: float, surplus: float, export_w: float) -> DecisionOutcome:
        return build_evening_sell_outcome(
            target_soc=target_soc,
            current_soc=current_soc,
            surplus_kwh=surplus,
            reserve_kwh=reserve_kwh,
            required_kwh=required_kwh,
            pv_forecast_kwh=pv_forecast_kwh,
            heat_pump_kwh=heat_pump_kwh,
            losses_kwh=losses_kwh,
            start_hour=start_hour,
            end_hour=end_hour,
            export_power_w=export_w,
            evening_price=evening_price,
            threshold_price=threshold_price,
        )

    def _make_no_action(_surplus: float) -> DecisionOutcome:
        return _build_no_action_outcome(
            reason="Calculated target SOC does not require discharge",
            current_soc=current_soc,
            evening_price=evening_price,
            threshold_price=threshold_price,
        )

    await _execute_sell(
        hass,
        entry=entry,
        config=config,
        bc=bc,
        current_soc=current_soc,
        surplus_kwh=surplus_kwh,
        prog5_soc_entity=prog5_soc_entity,
        integration_context=integration_context,
        build_outcome_fn=_make_outcome,
        build_no_action_fn=_make_no_action,
    )


async def _run_surplus_sell(
    hass: HomeAssistant,
    *,
    entry: ConfigEntry,
    config: dict[str, Any],
    current_soc: float,
    prog5_soc_entity: str,
    evening_price: float,
    threshold_price: float,
    margin: float,
    integration_context: Context,
) -> None:
    """Run sell logic for low-price surplus branch using two-window algorithm."""
    bc = get_battery_config(config)
    now_hour = dt_util.as_local(dt_util.utcnow()).hour

    hourly_usage = build_hourly_usage_array(
        config,
        hass.states.get,
        daily_load_fallback=None,
    )
    reserve_kwh = calculate_battery_reserve(
        current_soc,
        bc.min_soc,
        bc.capacity_ah,
        bc.voltage,
        efficiency=bc.efficiency,
    )

    tomorrow_end = resolve_tariff_end_hour(hass, config, default_hour=13)
    tomorrow_hp_kwh, tomorrow_hp_hourly = await get_heat_pump_forecast_window(
        hass,
        config,
        start_hour=0,
        end_hour=tomorrow_end,
    )
    tomorrow_pv_kwh, tomorrow_pv_hourly = get_pv_forecast_window(
        hass,
        config,
        start_hour=0,
        end_hour=tomorrow_end,
        apply_efficiency=True,
        compensate=True,
        entry_id=entry.entry_id,
    )
    tomorrow_losses_hourly, _ = calculate_losses(
        hass,
        config,
        hours=max(tomorrow_end, 1),
        margin=margin,
    )

    (
        _required_tomorrow_kwh,
        required_sufficiency_kwh,
        pv_sufficiency_kwh,
        sufficiency_hour,
        sufficiency_reached,
    ) = calculate_sufficiency_window(
        start_hour=0,
        end_hour=tomorrow_end,
        hourly_usage=hourly_usage,
        heat_pump_hourly=tomorrow_hp_hourly,
        losses_hourly=tomorrow_losses_hourly,
        margin=margin,
        pv_forecast_hourly=tomorrow_pv_hourly,
    )

    if not sufficiency_reached:
        outcome = _build_no_action_outcome(
            reason="Tomorrow PV does not reach sufficiency hour",
            current_soc=current_soc,
            evening_price=evening_price,
            threshold_price=threshold_price,
            sufficiency_hour=sufficiency_hour,
            sufficiency_reached=sufficiency_reached,
        )
        await log_decision_unified(
            hass,
            entry,
            outcome,
            context=integration_context,
            logger=_LOGGER,
        )
        return

    tomorrow_net_kwh = max(0.0, required_sufficiency_kwh - pv_sufficiency_kwh)

    today_start = (now_hour + 1) % 24
    today_end = 24
    today_window = build_hour_window(today_start, today_end)
    today_hours = max(len(today_window), 1)

    today_usage_kwh = sum(hourly_usage[hour] for hour in today_window)
    today_hp_kwh, _ = await get_heat_pump_forecast_window(
        hass,
        config,
        start_hour=today_start,
        end_hour=today_end,
    )
    today_pv_kwh, _ = get_pv_forecast_window(
        hass,
        config,
        start_hour=today_start,
        end_hour=today_end,
        apply_efficiency=True,
        compensate=True,
        entry_id=entry.entry_id,
    )
    _, today_losses_kwh = calculate_losses(
        hass,
        config,
        hours=today_hours,
        margin=margin,
    )

    today_required_kwh = (today_usage_kwh + today_hp_kwh + today_losses_kwh) * margin
    today_net_kwh = max(0.0, today_required_kwh - today_pv_kwh)

    total_needed_kwh = today_net_kwh + tomorrow_net_kwh
    surplus_kwh = max(0.0, reserve_kwh - total_needed_kwh)
    if surplus_kwh <= 0.0:
        outcome = _build_no_action_outcome(
            reason="No surplus energy available for surplus sell",
            current_soc=current_soc,
            evening_price=evening_price,
            threshold_price=threshold_price,
            sufficiency_hour=sufficiency_hour,
            sufficiency_reached=sufficiency_reached,
            surplus_kwh=surplus_kwh,
            total_needed_kwh=total_needed_kwh,
        )
        await log_decision_unified(
            hass,
            entry,
            outcome,
            context=integration_context,
            logger=_LOGGER,
        )
        return

    def _make_outcome(target_soc: float, surplus: float, export_w: float) -> DecisionOutcome:
        return build_surplus_sell_outcome(
            target_soc=target_soc,
            current_soc=current_soc,
            surplus_kwh=surplus,
            reserve_kwh=reserve_kwh,
            today_net_kwh=today_net_kwh,
            tomorrow_net_kwh=tomorrow_net_kwh,
            total_needed_kwh=total_needed_kwh,
            pv_today_kwh=today_pv_kwh,
            pv_tomorrow_kwh=tomorrow_pv_kwh,
            heat_pump_today_kwh=today_hp_kwh,
            heat_pump_tomorrow_kwh=tomorrow_hp_kwh,
            sufficiency_hour=sufficiency_hour,
            sufficiency_reached=sufficiency_reached,
            export_power_w=export_w,
            evening_price=evening_price,
            threshold_price=threshold_price,
        )

    def _make_no_action(current_surplus_kwh: float) -> DecisionOutcome:
        return _build_no_action_outcome(
            reason="Calculated target SOC does not require discharge",
            current_soc=current_soc,
            evening_price=evening_price,
            threshold_price=threshold_price,
            sufficiency_hour=sufficiency_hour,
            sufficiency_reached=sufficiency_reached,
            surplus_kwh=current_surplus_kwh,
            total_needed_kwh=total_needed_kwh,
        )

    await _execute_sell(
        hass,
        entry=entry,
        config=config,
        bc=bc,
        current_soc=current_soc,
        surplus_kwh=surplus_kwh,
        prog5_soc_entity=prog5_soc_entity,
        integration_context=integration_context,
        build_outcome_fn=_make_outcome,
        build_no_action_fn=_make_no_action,
    )