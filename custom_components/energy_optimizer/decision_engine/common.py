"""Shared helpers for decision engine modules."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..const import (
    CONF_BATTERY_SOC_SENSOR,
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG4_SOC_ENTITY,
    DOMAIN,
)
from ..helpers import get_required_float_state
from ..utils.logging import DecisionOutcome, format_sufficiency_hour

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


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
    target_soc: float,
    required_kwh: float,
    reserve_kwh: float,
    deficit_to_charge_kwh: float,
    deficit_all_kwh: float,
    pv_forecast_kwh: float,
    heat_pump_kwh: float,
    charge_current: float,
    current_soc: float,
    losses_kwh: float,
    efficiency: float,
    margin: float,
    pv_compensation_factor: float | None,
    start_hour: int,
    end_hour: int,
    arbitrage_kwh: float | None = None,
    usage_kwh: float | None = None,
    key_metrics_extra: dict[str, str] | None = None,
    full_details_extra: dict[str, float | str | int | bool | None] | None = None,
) -> DecisionOutcome:
    """Build the shared charge decision outcome payload."""
    summary = f"Battery scheduled to charge to {target_soc:.0f}%"
    if arbitrage_kwh is None:
        reason = (
            f"Deficit {deficit_to_charge_kwh:.1f} kWh, reserve {reserve_kwh:.1f} kWh, "
            f"required {required_kwh:.1f} kWh, PV {pv_forecast_kwh:.1f} kWh, "
            f"current {charge_current:.0f} A"
        )
    else:
        reason = (
            f"Deficit {deficit_to_charge_kwh:.1f} kWh, reserve {reserve_kwh:.1f} kWh, "
            f"required {required_kwh:.1f} kWh, PV {pv_forecast_kwh:.1f} kWh, "
            f"arbitrage {arbitrage_kwh:.1f} kWh, current {charge_current:.0f} A"
        )

    key_metrics = {
        "result": summary,
        "target": f"{target_soc:.0f}%",
        "required": f"{required_kwh:.1f} kWh",
        "reserve": f"{reserve_kwh:.1f} kWh",
        "to_charge": f"{deficit_to_charge_kwh:.1f} kWh",
        "pv": f"{pv_forecast_kwh:.1f} kWh",
        "heat_pump": f"{heat_pump_kwh:.1f} kWh",
        "charge_current": f"{charge_current:.0f} A",
        "window": f"{start_hour:02d}:00-{end_hour:02d}:00",
    }
    if arbitrage_kwh is not None:
        key_metrics["arbitrage"] = f"{arbitrage_kwh:.1f} kWh"
    if key_metrics_extra:
        key_metrics.update(key_metrics_extra)

    full_details = {
        "target_soc": round(target_soc, 1),
        "current_soc": round(current_soc, 1),
        "reserve": round(reserve_kwh, 2),
        "required": round(required_kwh, 2),
        "to_charge": round(deficit_to_charge_kwh, 2),
        "deficit": round(deficit_all_kwh, 2),
        "losses": round(losses_kwh, 2),
        "pv_forecast": round(pv_forecast_kwh, 2),
        "pv_compensation_factor": (
            round(pv_compensation_factor, 4)
            if pv_compensation_factor is not None
            else None
        ),
        "heat_pump": round(heat_pump_kwh, 2),
        "charge_current": round(charge_current, 1),
        "efficiency": round(efficiency, 1),
        "margin": margin,
    }
    if usage_kwh is not None:
        full_details["usage"] = round(usage_kwh, 2)
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
    target_soc: float,
    required_kwh: float,
    required_sufficiency_kwh: float,
    reserve_kwh: float,
    deficit_to_charge_kwh: float,
    deficit_all_kwh: float,
    deficit_kwh: float,
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
    pv_compensation_factor: float | None,
    start_hour: int,
    end_hour: int,
) -> DecisionOutcome:
    """Build a morning charge decision outcome."""
    key_metrics_extra = {
        "deficit": f"{deficit_kwh:.1f} kWh",
        "required_sufficiency": f"{required_sufficiency_kwh:.1f} kWh",
        "pv_sufficiency": f"{pv_sufficiency_kwh:.1f} kWh",
        "deficit_sufficiency": f"{deficit_sufficiency_kwh:.1f} kWh",
        "sufficiency_hour": format_sufficiency_hour(
            sufficiency_hour, sufficiency_reached=bool(sufficiency_reached)
        ),
    }
    full_details_extra = {
        "required_sufficiency": round(required_sufficiency_kwh, 2),
        "pv_sufficiency": round(pv_sufficiency_kwh, 2),
        "deficit_full": round(deficit_kwh, 2),
        "deficit_sufficiency": round(deficit_sufficiency_kwh, 2),
        "sufficiency_hour": sufficiency_hour,
        "sufficiency_reached": sufficiency_reached,
    }

    return build_charge_outcome_base(
        scenario=scenario,
        target_soc=target_soc,
        required_kwh=required_kwh,
        reserve_kwh=reserve_kwh,
        deficit_to_charge_kwh=deficit_to_charge_kwh,
        deficit_all_kwh=deficit_all_kwh,
        pv_forecast_kwh=pv_forecast_kwh,
        heat_pump_kwh=heat_pump_kwh,
        charge_current=charge_current,
        current_soc=current_soc,
        losses_kwh=losses_kwh,
        efficiency=efficiency,
        margin=margin,
        pv_compensation_factor=pv_compensation_factor,
        start_hour=start_hour,
        end_hour=end_hour,
        key_metrics_extra=key_metrics_extra,
        full_details_extra=full_details_extra,
    )


def build_afternoon_charge_outcome(
    *,
    scenario: str,
    target_soc: float,
    required_kwh: float,
    reserve_kwh: float,
    deficit_to_charge_kwh: float,
    deficit_all_kwh: float,
    arbitrage_kwh: float,
    arbitrage_details: dict[str, float | str] | None,
    pv_forecast_kwh: float,
    heat_pump_kwh: float,
    charge_current: float,
    current_soc: float,
    losses_kwh: float,
    efficiency: float,
    margin: float,
    start_hour: int,
    end_hour: int,
    usage_kwh: float,
    pv_compensation_factor: float | None,
) -> DecisionOutcome:
    """Build an afternoon charge decision outcome."""
    full_details_extra = {
        "start_hour": start_hour,
        "end_hour": end_hour,
        **(arbitrage_details or {}),
    }
    return build_charge_outcome_base(
        scenario=scenario,
        target_soc=target_soc,
        required_kwh=required_kwh,
        reserve_kwh=reserve_kwh,
        deficit_to_charge_kwh=deficit_to_charge_kwh,
        deficit_all_kwh=deficit_all_kwh,
        pv_forecast_kwh=pv_forecast_kwh,
        heat_pump_kwh=heat_pump_kwh,
        charge_current=charge_current,
        current_soc=current_soc,
        losses_kwh=losses_kwh,
        efficiency=efficiency,
        margin=margin,
        pv_compensation_factor=pv_compensation_factor,
        start_hour=start_hour,
        end_hour=end_hour,
        arbitrage_kwh=arbitrage_kwh,
        usage_kwh=usage_kwh,
        full_details_extra=full_details_extra,
    )


def build_charge_outcome(
    *,
    scenario: str,
    mode: str,
    target_soc: float,
    required_kwh: float,
    reserve_kwh: float,
    deficit_to_charge_kwh: float,
    pv_forecast_kwh: float,
    heat_pump_kwh: float,
    charge_current: float,
    current_soc: float,
    losses_kwh: float,
    efficiency: float,
    margin: float,
    pv_compensation_factor: float | None,
    required_sufficiency_kwh: float | None = None,
    pv_sufficiency_kwh: float | None = None,
    deficit_all_kwh: float | None = None,
    deficit_kwh: float | None = None,
    deficit_sufficiency_kwh: float | None = None,
    sufficiency_hour: int | None = None,
    sufficiency_reached: bool | None = None,
    arbitrage_kwh: float | None = None,
    arbitrage_details: dict[str, float | str] | None = None,
    start_hour: int | None = None,
    end_hour: int | None = None,
    usage_kwh: float | None = None,
) -> DecisionOutcome:
    """Build a charge decision outcome for morning or afternoon routines."""
    if start_hour is None or end_hour is None:
        raise ValueError("start_hour and end_hour are required for charge outcomes")

    if mode == "morning":
        if None in (
            required_sufficiency_kwh,
            pv_sufficiency_kwh,
            deficit_all_kwh,
            deficit_kwh,
            deficit_sufficiency_kwh,
            sufficiency_hour,
            sufficiency_reached,
        ):
            raise ValueError("missing morning charge outcome inputs")
        return build_morning_charge_outcome(
            scenario=scenario,
            target_soc=target_soc,
            required_kwh=required_kwh,
            required_sufficiency_kwh=required_sufficiency_kwh,
            reserve_kwh=reserve_kwh,
            deficit_to_charge_kwh=deficit_to_charge_kwh,
            deficit_all_kwh=deficit_all_kwh,
            deficit_kwh=deficit_kwh,
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
            pv_compensation_factor=pv_compensation_factor,
            start_hour=start_hour,
            end_hour=end_hour,
        )

    if None in (deficit_all_kwh, arbitrage_kwh, usage_kwh):
        raise ValueError("missing afternoon charge outcome inputs")

    return build_afternoon_charge_outcome(
        scenario=scenario,
        target_soc=target_soc,
        required_kwh=required_kwh,
        reserve_kwh=reserve_kwh,
        deficit_to_charge_kwh=deficit_to_charge_kwh,
        deficit_all_kwh=deficit_all_kwh,
        arbitrage_kwh=arbitrage_kwh,
        arbitrage_details=arbitrage_details,
        pv_forecast_kwh=pv_forecast_kwh,
        heat_pump_kwh=heat_pump_kwh,
        charge_current=charge_current,
        current_soc=current_soc,
        losses_kwh=losses_kwh,
        efficiency=efficiency,
        margin=margin,
        start_hour=start_hour,
        end_hour=end_hour,
        usage_kwh=usage_kwh,
        pv_compensation_factor=pv_compensation_factor,
    )
