"""Shared helpers for decision engine modules."""
from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any, Callable

from ..calculations.battery import (
    apply_efficiency_compensation,
    calculate_charge_current,
    calculate_soc_delta,
    calculate_target_soc,
    calculate_target_soc_from_reserve,
)
from ..calculations.energy import calculate_losses, calculate_sufficiency_window
from ..calculations.utils import build_hourly_usage_array
from ..controllers.inverter import set_program_soc
from ..const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_PROG3_SOC_ENTITY,
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG4_SOC_ENTITY,
    CONF_PROG5_SOC_ENTITY,
    DEFAULT_BATTERY_CAPACITY_AH,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_BATTERY_VOLTAGE,
    DEFAULT_MAX_SOC,
    DEFAULT_MIN_SOC,
    DOMAIN,
)
from ..helpers import get_required_float_state
from ..utils.forecast import get_heat_pump_forecast_window, get_pv_forecast_window
from ..utils.logging import DecisionOutcome, format_sufficiency_hour, log_decision_unified
from ..utils.time_window import build_hour_window

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import Context, HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class BatteryConfig:
    """Battery configuration extracted from config entry data."""

    capacity_ah: float
    voltage: float
    min_soc: float
    max_soc: float
    efficiency: float


@dataclasses.dataclass(frozen=True, slots=True)
class ForecastData:
    """PV, heat pump, usage and loss forecast data for a time window."""

    start_hour: int
    end_hour: int
    hours: int
    hourly_usage: list[float]
    usage_kwh: float
    heat_pump_kwh: float
    heat_pump_hourly: dict[int, float]
    pv_forecast_kwh: float
    pv_forecast_hourly: dict[int, float]
    losses_hourly: float
    losses_kwh: float
    margin: float


@dataclasses.dataclass(frozen=True, slots=True)
class SufficiencyResult:
    """Result of calculate_sufficiency_window for a time window."""

    required_kwh: float
    required_sufficiency_kwh: float
    pv_sufficiency_kwh: float
    sufficiency_hour: int
    sufficiency_reached: bool


@dataclasses.dataclass(frozen=True, slots=True)
class EnergyBalance:
    """Core energy balance for a decision window."""

    reserve_kwh: float
    required_kwh: float
    needed_reserve_kwh: float
    gap_kwh: float
    pv_compensation_factor: float | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class ChargeAction:
    """Charge calculation result reusable by morning and afternoon."""

    gap_to_charge_kwh: float
    soc_delta: float
    target_soc: float
    charge_current: float


def get_battery_config(config: dict[str, Any]) -> BatteryConfig:
    """Extract battery configuration from config entry data."""
    return BatteryConfig(
        capacity_ah=config.get(CONF_BATTERY_CAPACITY_AH, DEFAULT_BATTERY_CAPACITY_AH),
        voltage=config.get(CONF_BATTERY_VOLTAGE, DEFAULT_BATTERY_VOLTAGE),
        min_soc=config.get(CONF_MIN_SOC, DEFAULT_MIN_SOC),
        max_soc=config.get(CONF_MAX_SOC, DEFAULT_MAX_SOC),
        efficiency=config.get(CONF_BATTERY_EFFICIENCY, DEFAULT_BATTERY_EFFICIENCY),
    )


async def gather_forecasts(
    hass: HomeAssistant,
    config: dict[str, Any],
    *,
    start_hour: int,
    end_hour: int,
    margin: float,
    entry_id: str,
    apply_efficiency: bool = True,
    compensate: bool = True,
) -> ForecastData:
    """Gather all forecast data for a time window."""
    hour_window = build_hour_window(start_hour, end_hour)
    hours = max(len(hour_window), 1)

    hourly_usage = build_hourly_usage_array(
        config,
        hass.states.get,
        daily_load_fallback=None,
    )
    usage_kwh = sum(hourly_usage[hour] for hour in hour_window)

    heat_pump_kwh, heat_pump_hourly = await get_heat_pump_forecast_window(
        hass,
        config,
        start_hour=start_hour,
        end_hour=end_hour,
    )
    pv_forecast_kwh, pv_forecast_hourly = get_pv_forecast_window(
        hass,
        config,
        start_hour=start_hour,
        end_hour=end_hour,
        apply_efficiency=apply_efficiency,
        compensate=compensate,
        entry_id=entry_id,
    )
    losses_hourly, losses_kwh = calculate_losses(hass, config, hours=hours, margin=margin)

    return ForecastData(
        start_hour=start_hour,
        end_hour=end_hour,
        hours=hours,
        hourly_usage=hourly_usage,
        usage_kwh=usage_kwh,
        heat_pump_kwh=heat_pump_kwh,
        heat_pump_hourly=heat_pump_hourly,
        pv_forecast_kwh=pv_forecast_kwh,
        pv_forecast_hourly=pv_forecast_hourly,
        losses_hourly=losses_hourly,
        losses_kwh=losses_kwh,
        margin=margin,
    )


def compute_sufficiency(
    forecasts: ForecastData,
    *,
    calculator: Callable[..., tuple[float, float, float, int, bool]] = calculate_sufficiency_window,
) -> SufficiencyResult:
    """Compute sufficiency window from gathered forecasts."""
    (
        required_kwh,
        required_sufficiency_kwh,
        pv_sufficiency_kwh,
        sufficiency_hour,
        sufficiency_reached,
    ) = calculator(
        start_hour=forecasts.start_hour,
        end_hour=forecasts.end_hour,
        hourly_usage=forecasts.hourly_usage,
        heat_pump_hourly=forecasts.heat_pump_hourly,
        losses_hourly=forecasts.losses_hourly,
        margin=forecasts.margin,
        pv_forecast_hourly=forecasts.pv_forecast_hourly,
    )
    return SufficiencyResult(
        required_kwh=required_kwh,
        required_sufficiency_kwh=required_sufficiency_kwh,
        pv_sufficiency_kwh=pv_sufficiency_kwh,
        sufficiency_hour=sufficiency_hour,
        sufficiency_reached=sufficiency_reached,
    )


def calculate_charge_action(
    bc: BatteryConfig,
    *,
    gap_kwh: float,
    current_soc: float,
) -> ChargeAction:
    """Calculate charge parameters from energy gap."""
    gap_to_charge_kwh = apply_efficiency_compensation(gap_kwh, bc.efficiency)
    soc_delta = calculate_soc_delta(
        gap_to_charge_kwh,
        capacity_ah=bc.capacity_ah,
        voltage=bc.voltage,
    )
    target_soc = calculate_target_soc(current_soc, soc_delta, max_soc=bc.max_soc)
    charge_current = calculate_charge_current(
        gap_to_charge_kwh,
        current_soc=current_soc,
        capacity_ah=bc.capacity_ah,
        voltage=bc.voltage,
    )
    return ChargeAction(
        gap_to_charge_kwh=gap_to_charge_kwh,
        soc_delta=soc_delta,
        target_soc=target_soc,
        charge_current=charge_current,
    )


def calculate_target_soc_from_needed_reserve(
    *,
    needed_reserve_kwh: float,
    min_soc: float,
    max_soc: float,
    capacity_ah: float,
    voltage: float,
) -> float:
    """Calculate absolute target SOC from needed reserve for no-action paths."""
    return calculate_target_soc_from_reserve(
        needed_reserve_kwh=needed_reserve_kwh,
        min_soc=min_soc,
        max_soc=max_soc,
        capacity_ah=capacity_ah,
        voltage=voltage,
    )


def build_no_action_outcome(
    *,
    scenario: str,
    reason: str,
    summary: str = "No action needed",
    current_soc: float,
    reserve_kwh: float,
    required_kwh: float,
    pv_forecast_kwh: float,
    sufficiency_hour: int | None = None,
    sufficiency_reached: bool | None = None,
    key_metrics_extra: dict[str, str] | None = None,
    full_details_extra: dict[str, Any] | None = None,
) -> DecisionOutcome:
    """Build a shared no-action decision outcome payload."""
    key_metrics: dict[str, str] = {
        "result": summary,
        "current_soc": f"{current_soc:.0f}%",
        "reserve": f"{reserve_kwh:.1f} kWh",
        "required": f"{required_kwh:.1f} kWh",
        "pv": f"{pv_forecast_kwh:.1f} kWh",
    }
    full_details: dict[str, Any] = {
        "current_soc": round(current_soc, 1),
        "reserve_kwh": round(reserve_kwh, 2),
        "required_kwh": round(required_kwh, 2),
        "pv_forecast_kwh": round(pv_forecast_kwh, 2),
    }

    if sufficiency_hour is not None and sufficiency_reached is not None:
        key_metrics["sufficiency_hour"] = format_sufficiency_hour(
            sufficiency_hour,
            sufficiency_reached=sufficiency_reached,
        )
        full_details["sufficiency_hour"] = sufficiency_hour
        full_details["sufficiency_reached"] = sufficiency_reached

    if key_metrics_extra:
        key_metrics.update(key_metrics_extra)
    if full_details_extra:
        full_details.update(full_details_extra)

    return DecisionOutcome(
        scenario=scenario,
        action_type="no_action",
        summary=summary,
        reason=reason,
        key_metrics=key_metrics,
        full_details=full_details,
    )


async def handle_no_action_soc_update(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    integration_context: Context,
    prog_soc_entity: str,
    current_prog_soc: float,
    target_soc: float,
    outcome: DecisionOutcome,
) -> None:
    """Handle no-action path: conditionally update program SOC and log outcome."""
    entities_changed: list[dict[str, float | str]] = []
    if abs(target_soc - current_prog_soc) > 0.01:
        await set_program_soc(
            hass,
            prog_soc_entity,
            target_soc,
            entry=entry,
            logger=_LOGGER,
            context=integration_context,
        )
        entities_changed.append({"entity_id": prog_soc_entity, "value": target_soc})

    if entities_changed:
        outcome.entities_changed = entities_changed

    await log_decision_unified(
        hass, entry, outcome, context=integration_context, logger=_LOGGER
    )


def resolve_entry(hass: HomeAssistant, entry_id: str | None) -> ConfigEntry | None:
    """Resolve a config entry for the integration.

    If entry_id is provided, validates and returns the matching entry.
    If entry_id is None, returns the single entry if exactly one exists.
    """
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            _LOGGER.error("Invalid entry_id '%s' for %s", entry_id, DOMAIN)
            return None
        return entry

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        _LOGGER.error("No Energy Optimizer configuration found")
        return None
    if len(entries) > 1:
        _LOGGER.error(
            "Multiple %s config entries exist; service call must include entry_id",
            DOMAIN,
        )
        return None

    return entries[0]


def get_entry_data(hass: HomeAssistant, entry_id: str) -> dict[str, Any] | None:
    """Return runtime integration data dict for an entry, when available."""
    if (
        DOMAIN in hass.data
        and entry_id in hass.data[DOMAIN]
        and isinstance(hass.data[DOMAIN][entry_id], dict)
    ):
        return hass.data[DOMAIN][entry_id]
    return None


def get_required_prog2_soc_state(
    hass: HomeAssistant, config: dict[str, object]
) -> tuple[str, float] | None:
    """Return Program 2 SOC entity id and value when available."""
    prog2_soc_entity = config.get(CONF_PROG2_SOC_ENTITY)
    prog2_soc_value = get_required_float_state(
        hass,
        prog2_soc_entity,
        entity_name="Program 2 SOC entity",
    )
    if prog2_soc_value is None:
        return None
    return str(prog2_soc_entity), prog2_soc_value


def get_required_prog3_soc_state(
    hass: HomeAssistant, config: dict[str, object]
) -> tuple[str, float] | None:
    """Return Program 3 SOC entity id and value when available."""
    prog3_soc_entity = config.get(CONF_PROG3_SOC_ENTITY)
    prog3_soc_value = get_required_float_state(
        hass,
        prog3_soc_entity,
        entity_name="Program 3 SOC entity",
    )
    if prog3_soc_value is None:
        return None
    return str(prog3_soc_entity), prog3_soc_value


def get_required_prog4_soc_state(
    hass: HomeAssistant, config: dict[str, object]
) -> tuple[str, float] | None:
    """Return Program 4 SOC entity id and value when available."""
    prog4_soc_entity = config.get(CONF_PROG4_SOC_ENTITY)
    prog4_soc_value = get_required_float_state(
        hass,
        prog4_soc_entity,
        entity_name="Program 4 SOC entity",
    )
    if prog4_soc_value is None:
        return None
    return str(prog4_soc_entity), prog4_soc_value


def get_required_prog5_soc_state(
    hass: HomeAssistant, config: dict[str, object]
) -> tuple[str, float] | None:
    """Return Program 5 SOC entity id and value when available."""
    prog5_soc_entity = config.get(CONF_PROG5_SOC_ENTITY)
    prog5_soc_value = get_required_float_state(
        hass,
        prog5_soc_entity,
        entity_name="Program 5 SOC entity",
    )
    if prog5_soc_value is None:
        return None
    return str(prog5_soc_entity), prog5_soc_value


def get_required_current_soc_state(
    hass: HomeAssistant, config: dict[str, object]
) -> tuple[str, float] | None:
    """Return battery SOC entity id and value when available."""
    battery_soc_entity = config.get(CONF_BATTERY_SOC_SENSOR)
    current_soc = get_required_float_state(
        hass,
        battery_soc_entity,
        entity_name="Battery SOC sensor",
    )
    if current_soc is None:
        return None
    return str(battery_soc_entity), current_soc


def build_charge_outcome_base(
    *,
    scenario: str,
    action: ChargeAction,
    balance: EnergyBalance,
    forecasts: ForecastData,
    current_soc: float,
    efficiency: float,
    pv_compensation_factor: float | None,
    arbitrage_kwh: float | None = None,
    key_metrics_extra: dict[str, str] | None = None,
    full_details_extra: dict[str, float | str | int | bool | None] | None = None,
) -> DecisionOutcome:
    """Build the shared charge decision outcome payload."""
    summary = f"Battery scheduled to charge to {action.target_soc:.0f}%"
    if arbitrage_kwh is None:
        reason = (
            f"Gap {action.gap_to_charge_kwh:.1f} kWh, reserve {balance.reserve_kwh:.1f} kWh, "
            f"required {balance.required_kwh:.1f} kWh, PV {forecasts.pv_forecast_kwh:.1f} kWh, "
            f"current {action.charge_current:.0f} A"
        )
    else:
        reason = (
            f"Gap {action.gap_to_charge_kwh:.1f} kWh, reserve {balance.reserve_kwh:.1f} kWh, "
            f"required {balance.required_kwh:.1f} kWh, PV {forecasts.pv_forecast_kwh:.1f} kWh, "
            f"arbitrage {arbitrage_kwh:.1f} kWh, current {action.charge_current:.0f} A"
        )

    key_metrics = {
        "result": summary,
        "target": f"{action.target_soc:.0f}%",
        "required": f"{balance.required_kwh:.1f} kWh",
        "needed_reserve": f"{balance.needed_reserve_kwh:.1f} kWh",
        "reserve": f"{balance.reserve_kwh:.1f} kWh",
        "to_charge": f"{action.gap_to_charge_kwh:.1f} kWh",
        "pv": f"{forecasts.pv_forecast_kwh:.1f} kWh",
        "heat_pump": f"{forecasts.heat_pump_kwh:.1f} kWh",
        "charge_current": f"{action.charge_current:.0f} A",
        "window": f"{forecasts.start_hour:02d}:00-{forecasts.end_hour:02d}:00",
    }
    if arbitrage_kwh is not None:
        key_metrics["arbitrage"] = f"{arbitrage_kwh:.1f} kWh"
    if key_metrics_extra:
        key_metrics.update(key_metrics_extra)

    full_details = {
        "target_soc": round(action.target_soc, 1),
        "current_soc": round(current_soc, 1),
        "needed_reserve": round(balance.needed_reserve_kwh, 2),
        "reserve": round(balance.reserve_kwh, 2),
        "required": round(balance.required_kwh, 2),
        "to_charge": round(action.gap_to_charge_kwh, 2),
        "gap": round(balance.gap_kwh, 2),
        "losses": round(forecasts.losses_kwh, 2),
        "pv_forecast": round(forecasts.pv_forecast_kwh, 2),
        "pv_compensation_factor": (
            round(pv_compensation_factor, 4)
            if pv_compensation_factor is not None
            else None
        ),
        "heat_pump": round(forecasts.heat_pump_kwh, 2),
        "charge_current": round(action.charge_current, 1),
        "efficiency": round(efficiency, 1),
        "margin": forecasts.margin,
    }
    full_details["usage"] = round(forecasts.usage_kwh, 2)
    if arbitrage_kwh is not None:
        full_details["arbitrage"] = round(arbitrage_kwh, 2)
    if full_details_extra:
        full_details.update(full_details_extra)

    return DecisionOutcome(
        scenario=scenario,
        action_type="charge_scheduled",
        summary=summary,
        reason=reason,
        key_metrics=key_metrics,
        full_details=full_details,
    )


def build_morning_charge_outcome(
    *,
    scenario: str,
    action: ChargeAction,
    balance: EnergyBalance,
    forecasts: ForecastData,
    sufficiency: SufficiencyResult,
    needed_reserve_sufficiency_kwh: float,
    gap_sufficiency_kwh: float,
    current_soc: float,
    efficiency: float,
    pv_compensation_factor: float | None,
) -> DecisionOutcome:
    """Build a morning charge decision outcome."""
    key_metrics_extra = {
        "gap": f"{balance.gap_kwh:.1f} kWh",
        "needed_reserve_sufficiency": f"{needed_reserve_sufficiency_kwh:.1f} kWh",
        "required_sufficiency": f"{sufficiency.required_sufficiency_kwh:.1f} kWh",
        "pv_sufficiency": f"{sufficiency.pv_sufficiency_kwh:.1f} kWh",
        "gap_sufficiency": f"{gap_sufficiency_kwh:.1f} kWh",
        "sufficiency_hour": format_sufficiency_hour(
            sufficiency.sufficiency_hour,
            sufficiency_reached=sufficiency.sufficiency_reached,
        ),
    }
    full_details_extra = {
        "required_sufficiency": round(sufficiency.required_sufficiency_kwh, 2),
        "pv_sufficiency": round(sufficiency.pv_sufficiency_kwh, 2),
        "needed_reserve_sufficiency": round(needed_reserve_sufficiency_kwh, 2),
        "gap_full": round(balance.gap_kwh, 2),
        "gap_sufficiency": round(gap_sufficiency_kwh, 2),
        "sufficiency_hour": sufficiency.sufficiency_hour,
        "sufficiency_reached": sufficiency.sufficiency_reached,
    }

    return build_charge_outcome_base(
        scenario=scenario,
        action=action,
        balance=balance,
        forecasts=forecasts,
        current_soc=current_soc,
        efficiency=efficiency,
        pv_compensation_factor=pv_compensation_factor,
        key_metrics_extra=key_metrics_extra,
        full_details_extra=full_details_extra,
    )


def build_afternoon_charge_outcome(
    *,
    scenario: str,
    action: ChargeAction,
    balance: EnergyBalance,
    forecasts: ForecastData,
    arbitrage_kwh: float,
    arbitrage_details: dict[str, float | str] | None,
    current_soc: float,
    efficiency: float,
    pv_compensation_factor: float | None,
) -> DecisionOutcome:
    """Build an afternoon charge decision outcome."""
    full_details_extra = {
        "start_hour": forecasts.start_hour,
        "end_hour": forecasts.end_hour,
        **(arbitrage_details or {}),
    }
    return build_charge_outcome_base(
        scenario=scenario,
        action=action,
        balance=balance,
        forecasts=forecasts,
        current_soc=current_soc,
        efficiency=efficiency,
        pv_compensation_factor=pv_compensation_factor,
        arbitrage_kwh=arbitrage_kwh,
        full_details_extra=full_details_extra,
    )


def build_evening_sell_outcome(
    *,
    target_soc: float,
    current_soc: float,
    surplus_kwh: float,
    reserve_kwh: float,
    required_kwh: float,
    pv_forecast_kwh: float,
    heat_pump_kwh: float,
    losses_kwh: float,
    start_hour: int,
    end_hour: int,
    export_power_w: float,
    evening_price: float,
    threshold_price: float,
) -> DecisionOutcome:
    """Build an evening sell decision outcome."""
    summary = f"Battery scheduled to sell down to {target_soc:.0f}%"
    return DecisionOutcome(
        scenario="Evening Peak Sell",
        action_type="high_sell",
        summary=summary,
        reason=(
            f"Surplus {surplus_kwh:.1f} kWh, reserve {reserve_kwh:.1f} kWh, "
            f"required {required_kwh:.1f} kWh, PV {pv_forecast_kwh:.1f} kWh"
        ),
        key_metrics={
            "result": summary,
            "current_soc": f"{current_soc:.0f}%",
            "target_soc": f"{target_soc:.0f}%",
            "surplus": f"{surplus_kwh:.1f} kWh",
            "export_power": f"{export_power_w:.0f} W",
            "evening_price": f"{evening_price:.1f} PLN/MWh",
            "threshold_price": f"{threshold_price:.1f} PLN/MWh",
            "window": f"{start_hour:02d}:00-{end_hour:02d}:00",
        },
        full_details={
            "current_soc": round(current_soc, 1),
            "target_soc": round(target_soc, 1),
            "surplus_kwh": round(surplus_kwh, 2),
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "pv_forecast_kwh": round(pv_forecast_kwh, 2),
            "heat_pump_kwh": round(heat_pump_kwh, 2),
            "losses_kwh": round(losses_kwh, 2),
            "export_power_w": round(export_power_w, 0),
            "evening_price": round(evening_price, 2),
            "threshold_price": round(threshold_price, 2),
            "start_hour": start_hour,
            "end_hour": end_hour,
        },
    )


def build_surplus_sell_outcome(
    *,
    target_soc: float,
    current_soc: float,
    surplus_kwh: float,
    reserve_kwh: float,
    today_net_kwh: float,
    tomorrow_net_kwh: float,
    total_needed_kwh: float,
    pv_today_kwh: float,
    pv_tomorrow_kwh: float,
    heat_pump_today_kwh: float,
    heat_pump_tomorrow_kwh: float,
    sufficiency_hour: int,
    sufficiency_reached: bool,
    export_power_w: float,
    evening_price: float,
    threshold_price: float,
) -> DecisionOutcome:
    """Build a surplus-sell decision outcome."""
    summary = f"Surplus sell: battery scheduled to sell down to {target_soc:.0f}%"
    return DecisionOutcome(
        scenario="Evening Peak Sell",
        action_type="sell",
        summary=summary,
        reason=(
            f"Surplus {surplus_kwh:.1f} kWh, reserve {reserve_kwh:.1f} kWh, "
            f"today net {today_net_kwh:.1f} kWh, tomorrow net {tomorrow_net_kwh:.1f} kWh"
        ),
        key_metrics={
            "result": summary,
            "current_soc": f"{current_soc:.0f}%",
            "target_soc": f"{target_soc:.0f}%",
            "surplus": f"{surplus_kwh:.1f} kWh",
            "sufficiency_hour": format_sufficiency_hour(
                sufficiency_hour,
                sufficiency_reached=sufficiency_reached,
            ),
            "export_power": f"{export_power_w:.0f} W",
            "evening_price": f"{evening_price:.1f} PLN/MWh",
            "threshold_price": f"{threshold_price:.1f} PLN/MWh",
        },
        full_details={
            "current_soc": round(current_soc, 1),
            "target_soc": round(target_soc, 1),
            "surplus_kwh": round(surplus_kwh, 2),
            "reserve_kwh": round(reserve_kwh, 2),
            "today_net_kwh": round(today_net_kwh, 2),
            "tomorrow_net_kwh": round(tomorrow_net_kwh, 2),
            "total_needed_kwh": round(total_needed_kwh, 2),
            "pv_today_kwh": round(pv_today_kwh, 2),
            "pv_tomorrow_kwh": round(pv_tomorrow_kwh, 2),
            "heat_pump_today_kwh": round(heat_pump_today_kwh, 2),
            "heat_pump_tomorrow_kwh": round(heat_pump_tomorrow_kwh, 2),
            "sufficiency_hour": sufficiency_hour,
            "sufficiency_reached": sufficiency_reached,
            "export_power_w": round(export_power_w, 0),
            "evening_price": round(evening_price, 2),
            "threshold_price": round(threshold_price, 2),
        },
    )


