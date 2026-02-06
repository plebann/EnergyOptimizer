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
from ..utils.heat_pump import async_fetch_heat_pump_forecast_details
from ..utils.pv_forecast import get_pv_forecast_hourly_kwh, get_pv_forecast_kwh
from homeassistant.util import dt as dt_util

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
        if str(tariff_end_entity).startswith("input_datetime."):
            tariff_end_state = hass.states.get(str(tariff_end_entity))
            if tariff_end_state is None:
                _LOGGER.warning(
                    "Tariff end hour input_datetime %s unavailable, using default %s",
                    tariff_end_entity,
                    default_hour,
                )
            else:
                state_value = tariff_end_state.state
                dt_value = dt_util.parse_datetime(state_value)
                if dt_value is not None:
                    tariff_end_hour = dt_util.as_local(dt_value).hour
                else:
                    time_value = dt_util.parse_time(state_value)
                    if time_value is not None:
                        tariff_end_hour = time_value.hour
                    else:
                        _LOGGER.warning(
                            "Tariff end hour input_datetime %s has invalid value %s, using default %s",
                            tariff_end_entity,
                            state_value,
                            default_hour,
                        )
        else:
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


def _get_required_float_state(
    hass: HomeAssistant,
    entity_id: str | None,
    *,
    entity_name: str,
) -> float | None:
    """Fetch a required float state with logging and validation."""
    if not entity_id:
        _LOGGER.error("%s not configured", entity_name)
        return None

    value, raw, error = get_float_state_info(hass, entity_id)
    if error is not None or value is None:
        if error in ("missing", "unavailable"):
            _LOGGER.warning("%s %s unavailable", entity_name, entity_id)
        else:
            _LOGGER.warning("%s %s has invalid value: %s", entity_name, entity_id, raw)
        return None

    return value


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
    prog2_soc_value = _get_required_float_state(
        hass,
        prog2_soc_entity,
        entity_name="Program 2 SOC entity",
    )
    if prog2_soc_value is None:
        return

    if prog2_soc_value >= 100.0:
        _LOGGER.info("Program 2 SOC already at 100%%, skipping morning grid charge")
        return

    battery_soc_entity = config.get(CONF_BATTERY_SOC_SENSOR)
    current_soc = _get_required_float_state(
        hass,
        battery_soc_entity,
        entity_name="Battery SOC sensor",
    )
    if current_soc is None:
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

    start_hour = 6
    hours_morning = max(tariff_end_hour - start_hour, 1)
    heat_pump_kwh, heat_pump_hourly = await async_fetch_heat_pump_forecast_details(
        hass, config, starting_hour=start_hour, hours_ahead=hours_morning
    )
    if not heat_pump_hourly and heat_pump_kwh and hours_morning > 0:
        per_hour = heat_pump_kwh / hours_morning
        heat_pump_hourly = {
            hour: per_hour for hour in range(start_hour, tariff_end_hour)
        }

    pv_forecast_kwh = get_pv_forecast_kwh(
        hass,
        config,
        start_hour=start_hour,
        end_hour=tariff_end_hour,
    )
    pv_forecast_hourly = get_pv_forecast_hourly_kwh(
        hass,
        config,
        start_hour=start_hour,
        end_hour=tariff_end_hour,
    )

    losses_hourly = 0.0
    losses_entity = config.get(CONF_DAILY_LOSSES_SENSOR)
    if losses_entity:
        daily_losses = get_float_value(hass, losses_entity, default=0.0)
        if daily_losses:
            losses_hourly = (daily_losses / 24.0) * margin

    losses_kwh = losses_hourly * hours_morning

    def _hourly_demand(hour: int) -> float:
        return (
            (hourly_usage[hour] + heat_pump_hourly.get(hour, 0.0)) * margin
            + losses_hourly
        )

    required_kwh = sum(
        _hourly_demand(hour) for hour in range(start_hour, tariff_end_hour)
    )

    if required_kwh <= 0.0:
        _LOGGER.info("Required morning energy is zero or negative, skipping")
        return

    sufficiency_hour: int | None = None
    for hour in range(start_hour, tariff_end_hour):
        if pv_forecast_hourly.get(hour, 0.0) >= _hourly_demand(hour):
            sufficiency_hour = hour
            break

    sufficiency_reached = sufficiency_hour is not None
    if sufficiency_hour is None:
        sufficiency_hour = tariff_end_hour

    required_sufficiency_kwh = sum(
        _hourly_demand(hour) for hour in range(start_hour, sufficiency_hour)
    )
    pv_sufficiency_kwh = sum(
        pv_forecast_hourly.get(hour, 0.0)
        for hour in range(start_hour, sufficiency_hour)
    )

    deficit_full_kwh = required_kwh - reserve_kwh - pv_forecast_kwh
    deficit_sufficiency_kwh = (
        required_sufficiency_kwh - reserve_kwh - pv_sufficiency_kwh
    )
    deficit_kwh = max(deficit_full_kwh, deficit_sufficiency_kwh)

    if deficit_kwh <= 0.0:
        sufficiency_label = (
            f"{sufficiency_hour:02d}:00" if sufficiency_reached else "not reached"
        )
        outcome = DecisionOutcome(
            scenario="Morning Grid Charge",
            action_type="no_action",
            summary=f"No action needed",
            reason=(
                f"Deficit full {deficit_full_kwh:.1f} kWh, "
                f"deficit sufficiency {deficit_sufficiency_kwh:.1f} kWh"
            ),
            key_metrics={
                "result": "No action",
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
            "required_sufficiency": f"{required_sufficiency_kwh:.1f} kWh",
            "reserve": f"{reserve_kwh:.1f} kWh",
            "deficit": f"{deficit_to_charge_kwh:.1f} kWh",
            "deficit_full": f"{deficit_full_kwh:.1f} kWh",
            "deficit_sufficiency": f"{deficit_sufficiency_kwh:.1f} kWh",
            "pv": f"{pv_forecast_kwh:.1f} kWh",
            "pv_sufficiency": f"{pv_sufficiency_kwh:.1f} kWh",
            "heat_pump": f"{heat_pump_kwh:.1f} kWh",
            "current": f"{charge_current:.0f} A",
            "sufficiency_hour": (
                f"{sufficiency_hour:02d}:00" if sufficiency_reached else "not reached"
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
            "deficit_raw_kwh": round(deficit_kwh, 2),
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
        entities_changed=[
            {"entity_id": prog2_soc_entity, "value": target_soc},
            {"entity_id": charge_current_entity, "value": charge_current},
        ],
    )
    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )
