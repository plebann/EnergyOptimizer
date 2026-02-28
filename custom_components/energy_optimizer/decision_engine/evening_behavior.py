"""Evening behavior decision logic (overnight schedule)."""
from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import Context
from homeassistant.util import dt as dt_util

from ..calculations.battery import (
    calculate_battery_reserve,
    calculate_battery_space,
    calculate_target_soc_from_reserve,
)
from ..calculations.energy import (
    calculate_losses,
    calculate_needed_reserve_sufficiency,
    calculate_sufficiency_window,
)
from ..calculations.utils import build_hourly_usage_array
from ..const import (
    CONF_BALANCING_INTERVAL_DAYS,
    CONF_BALANCING_PV_THRESHOLD,
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_PROG1_SOC_ENTITY,
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG6_SOC_ENTITY,
    CONF_PV_FORECAST_TODAY,
    CONF_PV_FORECAST_TOMORROW,
    CONF_PV_PRODUCTION_SENSOR,
    DEFAULT_BALANCING_INTERVAL_DAYS,
    DEFAULT_BALANCING_PV_THRESHOLD,
    DEFAULT_MAX_CHARGE_CURRENT,
)
from ..controllers.inverter import set_max_charge_current, set_program_soc
from ..decision_engine.common import (
    get_battery_config,
    get_entry_data,
    get_required_current_soc_state,
    resolve_entry,
)
from ..helpers import get_float_state_info, resolve_tariff_end_hour
from ..utils.forecast import get_heat_pump_forecast_window, get_pv_forecast_window
from ..utils.logging import DecisionOutcome, format_sufficiency_hour, log_decision_unified
from ..utils.time_window import build_hour_window

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class BalancingData:
    """Balancing timing and PV forecast context."""

    balancing_due: bool
    days_since_balancing: int | None
    balancing_pv_threshold: float
    pv_forecast: float
    pv_with_efficiency: float


@dataclasses.dataclass(frozen=True, slots=True)
class PreservationContext:
    """Energy context for preservation and restoration decisions."""

    reserve_kwh: float
    required_kwh: float
    required_sufficiency_kwh: float
    pv_sufficiency_kwh: float
    needed_reserve_sufficiency_kwh: float
    sufficiency_hour: int
    sufficiency_reached: bool
    reserve_insufficient: bool
    grid_assist_on: bool
    battery_space: float
    pv_forecast_window_kwh: float
    heat_pump_window_kwh: float
    heat_pump_to_sufficiency_kwh: float
    morning_target_soc: float
    morning_needed_reserve_kwh: float


def _coerce_float(value: object | None) -> float | None:
    """Coerce arbitrary value to float when possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _update_pv_compensation(
    hass: HomeAssistant,
    config: dict[str, Any],
    *,
    entry_id: str,
) -> dict[str, float | None]:
    """Update PV compensation sensor and return details for logging."""
    entry_data = get_entry_data(hass, entry_id)
    if entry_data is None:
        return {}

    pv_compensation_sensor = entry_data.get("pv_forecast_compensation_sensor")
    if pv_compensation_sensor is None:
        return {}

    previous_attrs = pv_compensation_sensor.extra_state_attributes or {}
    forecast_yesterday = _coerce_float(previous_attrs.get("forecast_today_kwh"))
    production_yesterday = _coerce_float(previous_attrs.get("production_today_kwh"))

    forecast_today = None
    forecast_today_entity = config.get(CONF_PV_FORECAST_TODAY)
    if forecast_today_entity:
        forecast_value, forecast_raw, forecast_error = get_float_state_info(
            hass, forecast_today_entity
        )
        if forecast_error is None and forecast_value is not None:
            forecast_today = forecast_value
        elif forecast_error == "invalid":
            _LOGGER.warning("Could not parse PV forecast today: %s", forecast_raw)

    production_today = None
    production_entity = config.get(CONF_PV_PRODUCTION_SENSOR)
    if production_entity:
        production_value, production_raw, production_error = get_float_state_info(
            hass, production_entity
        )
        if production_error is None and production_value is not None:
            production_today = production_value
        elif production_error == "invalid":
            _LOGGER.warning("Could not parse PV production today: %s", production_raw)

    pv_compensation_sensor.update_compensation(
        forecast_today_kwh=forecast_today,
        production_today_kwh=production_today,
        forecast_yesterday_kwh=forecast_yesterday,
        production_yesterday_kwh=production_yesterday,
    )

    updated_attrs = pv_compensation_sensor.extra_state_attributes or {}
    return {
        "pv_compensation_factor": (
            float(pv_compensation_sensor.native_value)
            if pv_compensation_sensor.native_value is not None
            else None
        ),
        "pv_comp_forecast_today_kwh": updated_attrs.get("forecast_today_kwh"),
        "pv_comp_production_today_kwh": updated_attrs.get("production_today_kwh"),
        "pv_comp_forecast_yesterday_kwh": updated_attrs.get("forecast_yesterday_kwh"),
        "pv_comp_production_yesterday_kwh": updated_attrs.get(
            "production_yesterday_kwh"
        ),
    }


async def _handle_balancing(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    integration_context: Context,
    balancing_ongoing_sensor,
    balancing_due: bool,
    pv_with_efficiency: float,
    balancing_pv_threshold: float,
    days_since_balancing: int | None,
    prog1_soc: str | None,
    prog2_soc: str | None,
    prog6_soc: str | None,
    max_soc: float,
    max_charge_current_entity: str | None,
    pv_compensation_details: dict[str, float | None],
) -> bool:
    """Handle balancing scenario and return whether it was activated."""
    if not (balancing_due and pv_with_efficiency < balancing_pv_threshold):
        return False

    if balancing_ongoing_sensor is not None:
        balancing_ongoing_sensor.set_ongoing(True)
    _LOGGER.info(
        "Activating battery balancing mode (PV forecast with efficiency: %.2f kWh < %.2f kWh)",
        pv_with_efficiency,
        balancing_pv_threshold,
    )

    max_charge_current = DEFAULT_MAX_CHARGE_CURRENT
    await set_program_soc(
        hass,
        prog1_soc,
        max_soc,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )
    await set_program_soc(
        hass,
        prog2_soc,
        max_soc,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )
    await set_program_soc(
        hass,
        prog6_soc,
        max_soc,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )
    await set_max_charge_current(
        hass,
        max_charge_current_entity,
        max_charge_current,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )

    summary = "Balancing enabled"
    outcome = DecisionOutcome(
        scenario="Evening behavior",
        action_type="balancing_enabled",
        summary=summary,
        reason=f"Balancing treshold exceeded ({days_since_balancing} days)",
        details={
            "result": summary,
            "pv_with_efficiency_kwh": round(pv_with_efficiency, 2),
            "threshold_kwh": balancing_pv_threshold,
            "target_soc": max_soc,
            "days_since_last_balancing": days_since_balancing,
            **pv_compensation_details,
        },
        entities_changed=[
            {"entity_id": prog1_soc, "value": max_soc},
            {"entity_id": prog2_soc, "value": max_soc},
            {"entity_id": prog6_soc, "value": max_soc},
            {"entity_id": max_charge_current_entity, "value": max_charge_current},
        ],
    )
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )
    _LOGGER.info("Battery balancing mode activated")
    return True


async def _handle_preservation(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    integration_context: Context,
    grid_assist_on: bool,
    reserve_insufficient: bool,
    pv_with_efficiency: float,
    battery_space: float,
    prog1_soc: str | None,
    prog6_soc: str | None,
    current_soc: float,
    morning_target_soc: float,
    morning_needed_reserve_kwh: float,
    pv_forecast: float,
    heat_pump_window_kwh: float,
    heat_pump_to_sufficiency_kwh: float,
    reserve_kwh: float,
    required_kwh: float,
    required_sufficiency_kwh: float,
    pv_sufficiency_kwh: float,
    needed_reserve_sufficiency_kwh: float,
    sufficiency_hour: int,
    sufficiency_reached: bool,
    pv_forecast_window_kwh: float,
    pv_compensation_details: dict[str, float | None],
) -> bool:
    """Handle preservation scenario and return whether it was activated."""
    if not (grid_assist_on or reserve_insufficient or pv_with_efficiency < battery_space):
        return False

    reasons: list[str] = []
    if grid_assist_on:
        reasons.append("afternoon_grid_assist")
    if reserve_insufficient:
        reasons.append("reserve_insufficient")
    if pv_with_efficiency < battery_space:
        reasons.append("pv_insufficient")
    reason_detail = ", ".join(reasons) if reasons else "preservation_required"

    _LOGGER.info(
        "Activating battery preservation mode (PV %.2f kWh < space %.2f kWh)",
        pv_with_efficiency,
        battery_space,
    )

    await set_program_soc(
        hass,
        prog1_soc,
        morning_target_soc,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )
    await set_program_soc(
        hass,
        prog6_soc,
        morning_target_soc,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )

    summary = "Battery preservation mode"
    outcome = DecisionOutcome(
        scenario="Evening behavior",
        action_type="preservation_enabled",
        summary=summary,
        reason=(
            f"SOC target {morning_target_soc:.0f}%, PV: {pv_with_efficiency:.1f}, "
            f"battery space: {battery_space:.1f}, reason: {reason_detail}"
        ),
        details={
            "result": summary,
            "pv_forecast_kwh": round(pv_forecast, 2),
            "pv_forecast_window_kwh": round(pv_forecast_window_kwh, 2),
            "heat_pump_window_kwh": round(heat_pump_window_kwh, 2),
            "heat_pump_to_sufficiency_kwh": round(heat_pump_to_sufficiency_kwh, 2),
            "pv_with_efficiency_kwh": round(pv_with_efficiency, 2),
            "battery_space_kwh": round(battery_space, 2),
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "required_to_sufficiency_kwh": round(required_sufficiency_kwh, 2),
            "pv_to_sufficiency_kwh": round(pv_sufficiency_kwh, 2),
            "required_net_to_sufficiency_kwh": round(needed_reserve_sufficiency_kwh, 2),
            "sufficiency_hour": sufficiency_hour,
            "sufficiency_reached": sufficiency_reached,
            "reserve_insufficient": reserve_insufficient,
            "afternoon_grid_assist": grid_assist_on,
            "current_soc": round(current_soc, 1),
            "target_soc": round(morning_target_soc, 1),
            "morning_target_soc": round(morning_target_soc, 1),
            "morning_needed_reserve_kwh": round(morning_needed_reserve_kwh, 2),
            **pv_compensation_details,
        },
        entities_changed=[
            {"entity_id": prog1_soc, "value": morning_target_soc},
            {"entity_id": prog6_soc, "value": morning_target_soc},
        ],
    )
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )
    _LOGGER.info("Battery preservation mode activated")
    return True


async def _handle_normal_restoration(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    integration_context: Context,
    prog1_soc: str | None,
    prog2_soc: str | None,
    prog6_soc: str | None,
    min_soc: float,
    pv_forecast: float,
    heat_pump_window_kwh: float,
    heat_pump_to_sufficiency_kwh: float,
    battery_space: float,
    pv_with_efficiency: float,
    reserve_kwh: float,
    required_sufficiency_kwh: float,
    pv_sufficiency_kwh: float,
    needed_reserve_sufficiency_kwh: float,
    required_kwh: float,
    reserve_insufficient: bool,
    grid_assist_on: bool,
    sufficiency_hour: int,
    sufficiency_reached: bool,
) -> bool:
    """Handle normal restoration scenario and return whether it was activated."""
    current_prog6_soc = None
    if prog6_soc:
        prog6_value, prog6_raw, prog6_error = get_float_state_info(hass, prog6_soc)
        if prog6_error is None and prog6_value is not None:
            current_prog6_soc = prog6_value
        elif prog6_error == "invalid":
            _LOGGER.warning("Could not parse prog6 SOC: %s", prog6_raw)

    if current_prog6_soc is None or current_prog6_soc <= min_soc:
        return False

    _LOGGER.info(
        "Restoring normal operation (current: %.0f%%, restoring to: %.0f%%)",
        current_prog6_soc,
        min_soc,
    )

    await set_program_soc(
        hass,
        prog1_soc,
        min_soc,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )
    await set_program_soc(
        hass,
        prog2_soc,
        min_soc,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )
    await set_program_soc(
        hass,
        prog6_soc,
        min_soc,
        entry=entry,
        logger=_LOGGER,
        context=integration_context,
    )

    summary = "Normal operation restored"
    outcome = DecisionOutcome(
        scenario="Evening behavior",
        action_type="normal_restored",
        summary=summary,
        reason=f"PV within normal range, SOC minimum {min_soc:.0f}%",
        details={
            "result": summary,
            "previous": f"{current_prog6_soc:.0f}%",
            "previous_soc": round(current_prog6_soc, 1),
            "target_soc": min_soc,
            "pv_forecast_kwh": round(pv_forecast, 2),
            "heat_pump_window_kwh": round(heat_pump_window_kwh, 2),
            "heat_pump_to_sufficiency_kwh": round(heat_pump_to_sufficiency_kwh, 2),
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "required_to_sufficiency_kwh": round(required_sufficiency_kwh, 2),
            "pv_to_sufficiency_kwh": round(pv_sufficiency_kwh, 2),
            "required_net_to_sufficiency_kwh": round(needed_reserve_sufficiency_kwh, 2),
            "sufficiency_hour": sufficiency_hour,
            "sufficiency_reached": sufficiency_reached,
            "reserve_insufficient": reserve_insufficient,
            "afternoon_grid_assist": grid_assist_on,
        },
        entities_changed=[
            {"entity_id": prog1_soc, "value": min_soc},
            {"entity_id": prog2_soc, "value": min_soc},
            {"entity_id": prog6_soc, "value": min_soc},
        ],
    )
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )
    _LOGGER.info("Normal operation restored")
    return True


def _collect_balancing_data(
    hass: HomeAssistant,
    config: dict[str, Any],
    *,
    entry_id: str,
    last_balancing_sensor,
) -> BalancingData:
    """Collect balancing timing and forecast inputs."""
    balancing_interval_days = config.get(
        CONF_BALANCING_INTERVAL_DAYS, DEFAULT_BALANCING_INTERVAL_DAYS
    )
    balancing_pv_threshold = config.get(
        CONF_BALANCING_PV_THRESHOLD, DEFAULT_BALANCING_PV_THRESHOLD
    )

    last_balancing = (
        last_balancing_sensor.native_value if last_balancing_sensor else None
    )
    days_since_balancing = None
    if last_balancing:
        days_since_balancing = (dt_util.utcnow() - last_balancing).days
        _LOGGER.debug(
            "Days since last balancing: %s (last: %s)",
            days_since_balancing,
            last_balancing,
        )

    balancing_due = (last_balancing is None) or (
        days_since_balancing >= balancing_interval_days
    )

    pv_forecast = 0.0
    pv_forecast_entity = config.get(CONF_PV_FORECAST_TOMORROW)
    if pv_forecast_entity:
        pv_value, pv_raw, pv_error = get_float_state_info(hass, pv_forecast_entity)
        if pv_error is None and pv_value is not None:
            pv_forecast = pv_value
        elif pv_error == "invalid":
            _LOGGER.warning("Could not parse PV forecast: %s", pv_raw)

    pv_with_efficiency, _ = get_pv_forecast_window(
        hass,
        config,
        start_hour=0,
        end_hour=24,
        apply_efficiency=True,
        compensate=True,
        entry_id=entry_id,
    )
    _LOGGER.debug(
        "Balancing check: due=%s, pv_forecast_with_efficiency=%.2f kWh, threshold=%.2f kWh",
        balancing_due,
        pv_with_efficiency,
        balancing_pv_threshold,
    )

    return BalancingData(
        balancing_due=balancing_due,
        days_since_balancing=days_since_balancing,
        balancing_pv_threshold=balancing_pv_threshold,
        pv_forecast=pv_forecast,
        pv_with_efficiency=pv_with_efficiency,
    )


async def _calculate_preservation_context(
    hass: HomeAssistant,
    config: dict[str, Any],
    *,
    entry_id: str,
    current_soc: float,
    battery_config,
    margin: float,
    pv_with_efficiency: float,
    afternoon_grid_assist_sensor,
) -> PreservationContext:
    """Calculate energy context for preservation/restoration scenarios."""
    reserve_kwh = calculate_battery_reserve(
        current_soc,
        battery_config.min_soc,
        battery_config.capacity_ah,
        battery_config.voltage,
        efficiency=battery_config.efficiency,
    )
    hourly_usage = build_hourly_usage_array(config, hass.states.get, daily_load_fallback=None)
    start_hour = 22
    tariff_end_hour = resolve_tariff_end_hour(hass, config)
    hours = max(len(build_hour_window(start_hour, tariff_end_hour)), 1)

    heat_pump_window_kwh, heat_pump_hourly = await get_heat_pump_forecast_window(
        hass, config, start_hour=start_hour, end_hour=tariff_end_hour
    )
    pv_forecast_window_kwh, pv_forecast_hourly = get_pv_forecast_window(
        hass,
        config,
        start_hour=start_hour,
        end_hour=tariff_end_hour,
        apply_efficiency=True,
        compensate=True,
        entry_id=entry_id,
    )
    losses_hourly, _ = calculate_losses(hass, config, hours=hours)
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
    needed_reserve_sufficiency_kwh = calculate_needed_reserve_sufficiency(
        required_sufficiency_kwh,
        pv_sufficiency_kwh,
    )
    heat_pump_to_sufficiency_kwh = 0.0
    for hour in build_hour_window(start_hour, tariff_end_hour):
        if sufficiency_reached and hour == sufficiency_hour:
            break
        heat_pump_to_sufficiency_kwh += heat_pump_hourly.get(hour, 0.0)

    reserve_insufficient = reserve_kwh < needed_reserve_sufficiency_kwh

    MORNING_START_HOUR = 6
    morning_end_hour = sufficiency_hour if sufficiency_reached else tariff_end_hour
    if morning_end_hour > MORNING_START_HOUR:
        (
            _morning_required_kwh,
            morning_req_suff_kwh,
            morning_pv_suff_kwh,
            _morning_suff_hour,
            _morning_suff_reached,
        ) = calculate_sufficiency_window(
            start_hour=MORNING_START_HOUR,
            end_hour=morning_end_hour,
            hourly_usage=hourly_usage,
            heat_pump_hourly=heat_pump_hourly,
            losses_hourly=losses_hourly,
            margin=margin,
            pv_forecast_hourly=pv_forecast_hourly,
        )
        morning_needed_reserve_kwh = calculate_needed_reserve_sufficiency(
            morning_req_suff_kwh,
            morning_pv_suff_kwh,
        )
        unclamped_morning_target_soc = calculate_target_soc_from_reserve(
            needed_reserve_kwh=morning_needed_reserve_kwh,
            min_soc=battery_config.min_soc,
            max_soc=battery_config.max_soc,
            capacity_ah=battery_config.capacity_ah,
            voltage=battery_config.voltage,
        )
    else:
        morning_needed_reserve_kwh = 0.0
        unclamped_morning_target_soc = battery_config.min_soc

    morning_target_soc = min(unclamped_morning_target_soc, current_soc)

    grid_assist_on = bool(afternoon_grid_assist_sensor and afternoon_grid_assist_sensor.is_on)
    battery_space = calculate_battery_space(
        current_soc,
        battery_config.max_soc,
        battery_config.capacity_ah,
        battery_config.voltage,
    )

    _LOGGER.debug(
        "Battery space: %.2f kWh, PV forecast (90%%): %.2f kWh",
        battery_space,
        pv_with_efficiency,
    )
    _LOGGER.debug(
        "Reserve until sufficiency: reserve=%.2f kWh, needed_reserve=%.2f kWh, "
        "pv_to_sufficiency=%.2f kWh, heat_pump_to_sufficiency=%.2f kWh, "
        "sufficiency=%s, grid_assist=%s",
        reserve_kwh,
        needed_reserve_sufficiency_kwh,
        pv_sufficiency_kwh,
        heat_pump_to_sufficiency_kwh,
        format_sufficiency_hour(
            sufficiency_hour,
            sufficiency_reached=sufficiency_reached,
        ),
        grid_assist_on,
    )
    _LOGGER.debug(
        "Heat pump forecast in preservation window: %.2f kWh",
        heat_pump_window_kwh,
    )
    _LOGGER.debug(
        "Morning reserve target: morning_window=%02d:00-%02d:00, "
        "morning_needed_reserve=%.2f kWh, morning_target_soc=%.1f%% "
        "(clamped from %.1f%%)",
        MORNING_START_HOUR,
        morning_end_hour,
        morning_needed_reserve_kwh,
        morning_target_soc,
        unclamped_morning_target_soc,
    )

    return PreservationContext(
        reserve_kwh=reserve_kwh,
        required_kwh=required_kwh,
        required_sufficiency_kwh=required_sufficiency_kwh,
        pv_sufficiency_kwh=pv_sufficiency_kwh,
        needed_reserve_sufficiency_kwh=needed_reserve_sufficiency_kwh,
        sufficiency_hour=sufficiency_hour,
        sufficiency_reached=sufficiency_reached,
        reserve_insufficient=reserve_insufficient,
        grid_assist_on=grid_assist_on,
        battery_space=battery_space,
        pv_forecast_window_kwh=pv_forecast_window_kwh,
        heat_pump_window_kwh=heat_pump_window_kwh,
        heat_pump_to_sufficiency_kwh=heat_pump_to_sufficiency_kwh,
        morning_target_soc=morning_target_soc,
        morning_needed_reserve_kwh=morning_needed_reserve_kwh,
    )


async def _run_non_balancing_flow(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    config: dict[str, Any],
    integration_context: Context,
    battery_config,
    prog1_soc: str | None,
    prog2_soc: str | None,
    prog6_soc: str | None,
    balancing_data: BalancingData,
    pv_compensation_details: dict[str, float | None],
    afternoon_grid_assist_sensor,
) -> None:
    """Handle preservation, restoration and no-action branches."""
    _LOGGER.debug("Balancing not triggered - checking preservation/normal operation modes")
    current_soc_state = get_required_current_soc_state(hass, config)
    if current_soc_state is None:
        _LOGGER.warning("Current battery SOC not available, skipping preservation check")
        return

    _, current_soc = current_soc_state
    if current_soc < battery_config.min_soc:
        _LOGGER.info(
            "Current SOC %.1f%% below minimum %.1f%%, using min_soc as lock target",
            current_soc,
            battery_config.min_soc,
        )
        current_soc = battery_config.min_soc

    preservation = await _calculate_preservation_context(
        hass,
        config,
        entry_id=entry.entry_id,
        current_soc=current_soc,
        battery_config=battery_config,
        margin=1.1,
        pv_with_efficiency=balancing_data.pv_with_efficiency,
        afternoon_grid_assist_sensor=afternoon_grid_assist_sensor,
    )

    if await _handle_preservation(
        hass,
        entry,
        integration_context=integration_context,
        grid_assist_on=preservation.grid_assist_on,
        reserve_insufficient=preservation.reserve_insufficient,
        pv_with_efficiency=balancing_data.pv_with_efficiency,
        battery_space=preservation.battery_space,
        prog1_soc=prog1_soc,
        prog6_soc=prog6_soc,
        current_soc=current_soc,
        morning_target_soc=preservation.morning_target_soc,
        morning_needed_reserve_kwh=preservation.morning_needed_reserve_kwh,
        pv_forecast=balancing_data.pv_forecast,
        heat_pump_window_kwh=preservation.heat_pump_window_kwh,
        heat_pump_to_sufficiency_kwh=preservation.heat_pump_to_sufficiency_kwh,
        reserve_kwh=preservation.reserve_kwh,
        required_kwh=preservation.required_kwh,
        required_sufficiency_kwh=preservation.required_sufficiency_kwh,
        pv_sufficiency_kwh=preservation.pv_sufficiency_kwh,
        needed_reserve_sufficiency_kwh=preservation.needed_reserve_sufficiency_kwh,
        sufficiency_hour=preservation.sufficiency_hour,
        sufficiency_reached=preservation.sufficiency_reached,
        pv_forecast_window_kwh=preservation.pv_forecast_window_kwh,
        pv_compensation_details=pv_compensation_details,
    ):
        return

    if await _handle_normal_restoration(
        hass,
        entry,
        integration_context=integration_context,
        prog1_soc=prog1_soc,
        prog2_soc=prog2_soc,
        prog6_soc=prog6_soc,
        min_soc=battery_config.min_soc,
        pv_forecast=balancing_data.pv_forecast,
        heat_pump_window_kwh=preservation.heat_pump_window_kwh,
        heat_pump_to_sufficiency_kwh=preservation.heat_pump_to_sufficiency_kwh,
        battery_space=preservation.battery_space,
        pv_with_efficiency=balancing_data.pv_with_efficiency,
        reserve_kwh=preservation.reserve_kwh,
        required_sufficiency_kwh=preservation.required_sufficiency_kwh,
        pv_sufficiency_kwh=preservation.pv_sufficiency_kwh,
        needed_reserve_sufficiency_kwh=preservation.needed_reserve_sufficiency_kwh,
        required_kwh=preservation.required_kwh,
        reserve_insufficient=preservation.reserve_insufficient,
        grid_assist_on=preservation.grid_assist_on,
        sufficiency_hour=preservation.sufficiency_hour,
        sufficiency_reached=preservation.sufficiency_reached,
    ):
        return

    outcome = DecisionOutcome(
        scenario="Evening behavior",
        action_type="no_action",
        summary="No action",
        reason="Battery state within acceptable parameters",
        details={
            "result": "No action",
            "pv_forecast_kwh": round(balancing_data.pv_forecast, 2),
            "battery_space_kwh": round(preservation.battery_space, 2),
            "heat_pump_window_kwh": round(preservation.heat_pump_window_kwh, 2),
            "heat_pump_to_sufficiency_kwh": round(
                preservation.heat_pump_to_sufficiency_kwh,
                2,
            ),
            "target_soc": round(current_soc, 1) if current_soc else 0,
            "reserve_kwh": round(preservation.reserve_kwh, 2),
            "required_kwh": round(preservation.required_kwh, 2),
            "required_to_sufficiency_kwh": round(
                preservation.required_sufficiency_kwh,
                2,
            ),
            "pv_to_sufficiency_kwh": round(preservation.pv_sufficiency_kwh, 2),
            "required_net_to_sufficiency_kwh": round(
                preservation.needed_reserve_sufficiency_kwh,
                2,
            ),
            "sufficiency_hour": preservation.sufficiency_hour,
            "sufficiency_reached": preservation.sufficiency_reached,
            "reserve_insufficient": preservation.reserve_insufficient,
            "afternoon_grid_assist": preservation.grid_assist_on,
            **pv_compensation_details,
        },
    )
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )
    _LOGGER.debug("No battery schedule changes needed")


async def async_run_evening_behavior(
    hass: HomeAssistant, *, entry_id: str | None = None
) -> None:
    """Run overnight schedule logic (22:00 behavior)."""
    _LOGGER.info("=== Battery Overnight Handling Started ===")
    integration_context = Context()

    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    config = entry.data
    bc = get_battery_config(config)

    pv_compensation_details = _update_pv_compensation(
        hass,
        config,
        entry_id=entry.entry_id,
    )

    prog1_soc = config.get(CONF_PROG1_SOC_ENTITY)
    prog2_soc = config.get(CONF_PROG2_SOC_ENTITY)
    prog6_soc = config.get(CONF_PROG6_SOC_ENTITY)
    max_charge_current_entity = config.get(CONF_MAX_CHARGE_CURRENT_ENTITY)

    entry_data = get_entry_data(hass, entry.entry_id)
    last_balancing_sensor = None if entry_data is None else entry_data.get("last_balancing_sensor")
    balancing_ongoing_sensor = (
        None if entry_data is None else entry_data.get("balancing_ongoing_sensor")
    )
    afternoon_grid_assist_sensor = (
        None if entry_data is None else entry_data.get("afternoon_grid_assist_sensor")
    )
    if last_balancing_sensor is None:
        _LOGGER.warning(
            "Last balancing sensor not yet initialized. "
            "Balancing timestamp will not be updated this run."
        )

    balancing_data = _collect_balancing_data(
        hass,
        config,
        entry_id=entry.entry_id,
        last_balancing_sensor=last_balancing_sensor,
    )

    if balancing_ongoing_sensor is not None:
        balancing_ongoing_sensor.set_ongoing(False)

    if await _handle_balancing(
        hass,
        entry,
        integration_context=integration_context,
        balancing_ongoing_sensor=balancing_ongoing_sensor,
        balancing_due=balancing_data.balancing_due,
        pv_with_efficiency=balancing_data.pv_with_efficiency,
        balancing_pv_threshold=balancing_data.balancing_pv_threshold,
        days_since_balancing=balancing_data.days_since_balancing,
        prog1_soc=prog1_soc,
        prog2_soc=prog2_soc,
        prog6_soc=prog6_soc,
        max_soc=bc.max_soc,
        max_charge_current_entity=max_charge_current_entity,
        pv_compensation_details=pv_compensation_details,
    ):
        return

    await _run_non_balancing_flow(
        hass,
        entry,
        config=config,
        integration_context=integration_context,
        battery_config=bc,
        prog1_soc=prog1_soc,
        prog2_soc=prog2_soc,
        prog6_soc=prog6_soc,
        balancing_data=balancing_data,
        pv_compensation_details=pv_compensation_details,
        afternoon_grid_assist_sensor=afternoon_grid_assist_sensor,
    )