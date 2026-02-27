"""Morning peak sell decision logic."""
from __future__ import annotations

from collections.abc import Callable
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import Context
from homeassistant.helpers.storage import Store
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
    CONF_EXPORT_POWER_ENTITY,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_MORNING_MAX_PRICE_SENSOR,
    CONF_PV_PRODUCTION_SENSOR,
    CONF_WORK_MODE_ENTITY,
    DOMAIN,
    STORAGE_KEY_SELL_RESTORE,
    STORAGE_VERSION_SELL_RESTORE,
)
from ..controllers.inverter import set_export_power, set_program_soc, set_work_mode
from ..decision_engine.common import (
    ForecastData,
    build_evening_sell_outcome,
    build_no_action_outcome,
    compute_sufficiency,
    get_battery_config,
    get_required_current_soc_state,
    get_required_prog3_soc_state,
    resolve_entry,
)
from ..helpers import (
    get_float_state_info,
    get_required_float_state,
    is_test_sell_mode,
    resolve_morning_max_price_hour,
    resolve_tariff_end_hour,
)
from ..utils.forecast import get_heat_pump_forecast_window, get_pv_forecast_window
from ..utils.logging import DecisionOutcome, log_decision_unified
from ..utils.time_window import build_hour_window

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def _execute_sell(
    hass: HomeAssistant,
    *,
    entry: ConfigEntry,
    config: dict[str, Any],
    bc: Any,
    current_soc: float,
    surplus_kwh: float,
    prog3_soc_entity: str,
    original_prog_soc: float,
    restore_hour: int,
    sell_type: str,
    integration_context: Context,
    build_outcome_fn: Callable[[float, float, float], DecisionOutcome],
    build_no_action_fn: Callable[[float], DecisionOutcome],
) -> None:
    """Execute shared sell tail: target, writes, outcome and logging."""

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
    original_work_mode: str | None = None
    if work_mode_entity:
        wm_state = hass.states.get(str(work_mode_entity))
        if wm_state is not None:
            original_work_mode = wm_state.state

    if sell_test_mode:
        _LOGGER.info("Test sell mode enabled - skipping morning sell inverter writes")
    else:
        await set_work_mode(
            hass,
            str(work_mode_entity) if work_mode_entity else None,
            "Export First",
            entry=entry,
            logger=_LOGGER,
            context=integration_context,
        )

        restore_data = {
            "work_mode": original_work_mode,
            "prog_soc_entity": prog3_soc_entity,
            "prog_soc_value": original_prog_soc,
            "restore_hour": restore_hour,
            "sell_type": sell_type,
            "timestamp": dt_util.utcnow().isoformat(),
        }
        hass.data[DOMAIN][entry.entry_id]["sell_restore"] = restore_data
        store = Store(
            hass,
            STORAGE_VERSION_SELL_RESTORE,
            f"{STORAGE_KEY_SELL_RESTORE}.{entry.entry_id}",
        )
        await store.async_save(restore_data)
        await set_program_soc(
            hass,
            prog3_soc_entity,
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
        outcome.entities_changed = [{"entity_id": prog3_soc_entity, "value": target_soc}]
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


async def async_run_morning_sell(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    margin: float | None = None,
) -> None:
    """Run morning peak sell routine."""
    integration_context = Context()

    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    config = entry.data

    current_soc_state = get_required_current_soc_state(hass, config)
    if current_soc_state is None:
        return
    _, current_soc = current_soc_state

    prog3_soc_state = get_required_prog3_soc_state(hass, config)
    if prog3_soc_state is None:
        return
    prog3_soc_entity, original_prog3_soc = prog3_soc_state
    sell_hour = resolve_morning_max_price_hour(hass, config, default_hour=7)
    restore_hour = (sell_hour + 1) % 24

    morning_price = get_required_float_state(
        hass,
        config.get(CONF_MORNING_MAX_PRICE_SENSOR),
        entity_name="Morning max price sensor",
    )
    if morning_price is None:
        return

    threshold_price = float(config.get(CONF_MIN_ARBITRAGE_PRICE, 0.0) or 0.0)
    effective_margin = margin if margin is not None else 1.1

    await _run_morning_surplus_sell(
        hass,
        entry=entry,
        config=config,
        current_soc=current_soc,
        prog3_soc_entity=prog3_soc_entity,
        original_prog3_soc=original_prog3_soc,
        restore_hour=restore_hour,
        morning_price=morning_price,
        threshold_price=threshold_price,
        margin=effective_margin,
        integration_context=integration_context,
    )


async def _run_morning_surplus_sell(
    hass: HomeAssistant,
    *,
    entry: ConfigEntry,
    config: dict[str, Any],
    current_soc: float,
    prog3_soc_entity: str,
    original_prog3_soc: float,
    restore_hour: int,
    morning_price: float,
    threshold_price: float,
    margin: float,
    integration_context: Context,
) -> None:
    """Run morning sell logic using a single surplus branch."""
    battery_config = get_battery_config(config)
    now_hour = dt_util.as_local(dt_util.utcnow()).hour
    start_hour = (now_hour + 1) % 24
    base_end_hour = resolve_tariff_end_hour(hass, config, default_hour=13)

    hourly_usage = build_hourly_usage_array(
        config,
        hass.states.get,
        daily_load_fallback=None,
    )

    base_window = build_hour_window(start_hour, base_end_hour)
    base_hours = max(len(base_window), 1)
    base_usage_kwh = sum(hourly_usage[hour] for hour in base_window)
    base_heat_pump_kwh, base_heat_pump_hourly = await get_heat_pump_forecast_window(
        hass,
        config,
        start_hour=start_hour,
        end_hour=base_end_hour,
    )
    base_pv_forecast_kwh, base_pv_forecast_hourly = get_pv_forecast_window(
        hass,
        config,
        start_hour=start_hour,
        end_hour=base_end_hour,
        apply_efficiency=False,
        compensate=True,
        entry_id=entry.entry_id,
    )
    base_losses_hourly, base_losses_kwh = calculate_losses(
        hass,
        config,
        hours=base_hours,
        margin=margin,
    )

    base_forecasts = ForecastData(
        start_hour=start_hour,
        end_hour=base_end_hour,
        hours=base_hours,
        hourly_usage=hourly_usage,
        usage_kwh=base_usage_kwh,
        heat_pump_kwh=base_heat_pump_kwh,
        heat_pump_hourly=base_heat_pump_hourly,
        pv_forecast_kwh=base_pv_forecast_kwh,
        pv_forecast_hourly=base_pv_forecast_hourly,
        losses_hourly=base_losses_hourly,
        losses_kwh=base_losses_kwh,
        margin=margin,
    )
    sufficiency = compute_sufficiency(
        base_forecasts,
        calculator=calculate_sufficiency_window,
    )

    effective_end_hour = base_end_hour
    if sufficiency.sufficiency_reached:
        effective_end_hour = min(sufficiency.sufficiency_hour, base_end_hour)

    effective_window = build_hour_window(start_hour, effective_end_hour)
    effective_hours = max(len(effective_window), 1)
    usage_kwh = sum(hourly_usage[hour] for hour in effective_window)
    heat_pump_kwh = sum(base_heat_pump_hourly.get(hour, 0.0) for hour in effective_window)
    pv_forecast_kwh = sum(base_pv_forecast_hourly.get(hour, 0.0) for hour in effective_window)
    losses_kwh = base_losses_hourly * effective_hours

    required_kwh = (usage_kwh + heat_pump_kwh + losses_kwh) * margin
    reserve_kwh = calculate_battery_reserve(
        current_soc,
        battery_config.min_soc,
        battery_config.capacity_ah,
        battery_config.voltage,
        efficiency=battery_config.efficiency,
    )
    surplus_kwh = calculate_surplus_energy(
        reserve_kwh,
        required_kwh,
        pv_forecast_kwh,
    )

    if surplus_kwh <= 0.0:
        outcome = build_no_action_outcome(
            scenario="Morning Peak Sell",
            summary="No morning peak sell action",
            reason="No surplus energy available for selling",
            current_soc=current_soc,
            reserve_kwh=reserve_kwh,
            required_kwh=required_kwh,
            pv_forecast_kwh=pv_forecast_kwh,
            sufficiency_hour=sufficiency.sufficiency_hour,
            sufficiency_reached=sufficiency.sufficiency_reached,
            key_metrics_extra={
                "morning_price": f"{morning_price:.1f} PLN/MWh",
                "threshold_price": f"{threshold_price:.1f} PLN/MWh",
                "window": f"{start_hour:02d}:00-{effective_end_hour:02d}:00",
            },
            full_details_extra={
                "morning_price": round(morning_price, 2),
                "threshold_price": round(threshold_price, 2),
                "start_hour": start_hour,
                "end_hour": effective_end_hour,
            },
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
        return build_evening_sell_outcome(
            scenario="Morning Peak Sell",
            action_type="sell",
            price_metric_key="morning_price",
            threshold_metric_key="threshold_price",
            target_soc=target_soc,
            current_soc=current_soc,
            surplus_kwh=surplus,
            reserve_kwh=reserve_kwh,
            required_kwh=required_kwh,
            pv_forecast_kwh=pv_forecast_kwh,
            heat_pump_kwh=heat_pump_kwh,
            losses_kwh=losses_kwh,
            start_hour=start_hour,
            end_hour=effective_end_hour,
            export_power_w=export_w,
            evening_price=morning_price,
            threshold_price=threshold_price,
        )

    def _make_no_action(current_surplus_kwh: float) -> DecisionOutcome:
        return build_no_action_outcome(
            scenario="Morning Peak Sell",
            summary="No morning peak sell action",
            reason="Calculated target SOC does not require discharge",
            current_soc=current_soc,
            reserve_kwh=reserve_kwh,
            required_kwh=required_kwh,
            pv_forecast_kwh=pv_forecast_kwh,
            sufficiency_hour=sufficiency.sufficiency_hour,
            sufficiency_reached=sufficiency.sufficiency_reached,
            key_metrics_extra={
                "morning_price": f"{morning_price:.1f} PLN/MWh",
                "threshold_price": f"{threshold_price:.1f} PLN/MWh",
                "surplus": f"{current_surplus_kwh:.1f} kWh",
                "window": f"{start_hour:02d}:00-{effective_end_hour:02d}:00",
            },
            full_details_extra={
                "morning_price": round(morning_price, 2),
                "threshold_price": round(threshold_price, 2),
                "surplus_kwh": round(current_surplus_kwh, 2),
                "start_hour": start_hour,
                "end_hour": effective_end_hour,
            },
        )

    await _execute_sell(
        hass,
        entry=entry,
        config=config,
        bc=battery_config,
        current_soc=current_soc,
        surplus_kwh=surplus_kwh,
        prog3_soc_entity=prog3_soc_entity,
        original_prog_soc=original_prog3_soc,
        restore_hour=restore_hour,
        sell_type="morning",
        integration_context=integration_context,
        build_outcome_fn=_make_outcome,
        build_no_action_fn=_make_no_action,
    )
