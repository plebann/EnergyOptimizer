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

    if mode == "morning":
        key_metrics = {
            "result": summary,
            "target": f"{target_soc:.0f}%",
            "required": f"{required_kwh:.1f} kWh",
            "required_sufficiency": f"{required_sufficiency_kwh:.1f} kWh",
            "reserve": f"{reserve_kwh:.1f} kWh",
            "deficit": f"{deficit_to_charge_kwh:.1f} kWh",
            "deficit_full": f"{deficit_kwh:.1f} kWh",
            "deficit_sufficiency": f"{deficit_sufficiency_kwh:.1f} kWh",
            "pv": f"{pv_forecast_kwh:.1f} kWh",
            "pv_sufficiency": f"{pv_sufficiency_kwh:.1f} kWh",
            "heat_pump": f"{heat_pump_kwh:.1f} kWh",
            "current": f"{charge_current:.0f} A",
            "sufficiency_hour": format_sufficiency_hour(
                sufficiency_hour, sufficiency_reached=bool(sufficiency_reached)
            ),
        }
        full_details = {
            "target_soc": round(target_soc, 1),
            "current_soc": round(current_soc, 1),
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "required_sufficiency_kwh": round(required_sufficiency_kwh, 2),
            "pv_sufficiency_kwh": round(pv_sufficiency_kwh, 2),
            "deficit_kwh": round(deficit_to_charge_kwh, 2),
            "deficit_raw_kwh": round(deficit_all_kwh, 2),
            "deficit_full_kwh": round(deficit_kwh, 2),
            "deficit_sufficiency_kwh": round(deficit_sufficiency_kwh, 2),
            "losses_kwh": round(losses_kwh, 2),
            "pv_forecast_kwh": round(pv_forecast_kwh, 2),
            "pv_compensation_factor": (
                round(pv_compensation_factor, 4)
                if pv_compensation_factor is not None
                else None
            ),
            "heat_pump_kwh": round(heat_pump_kwh, 2),
            "charge_current_a": round(charge_current, 1),
            "efficiency": round(efficiency, 1),
            "margin": margin,
            "sufficiency_hour": sufficiency_hour,
            "sufficiency_reached": sufficiency_reached,
        }
    else:
        key_metrics = {
            "target": f"{target_soc:.0f}%",
            "result": summary,
            "required": f"{required_kwh:.1f} kWh",
            "reserve": f"{reserve_kwh:.1f} kWh",
            "deficit": f"{deficit_to_charge_kwh:.1f} kWh",
            "arbitrage": f"{arbitrage_kwh:.1f} kWh",
            "pv": f"{pv_forecast_kwh:.1f} kWh",
            "heat_pump": f"{heat_pump_kwh:.1f} kWh",
            "current": f"{charge_current:.0f} A",
            "window": f"{start_hour:02d}:00-{end_hour:02d}:00",
        }
        full_details = {
            "target_soc": round(target_soc, 1),
            "current_soc": round(current_soc, 1),
            "reserve_kwh": round(reserve_kwh, 2),
            "required_kwh": round(required_kwh, 2),
            "usage_kwh": round(usage_kwh, 2),
            "deficit_kwh": round(deficit_to_charge_kwh, 2),
            "deficit_raw_kwh": round(deficit_all_kwh, 2),
            "arbitrage_kwh": round(arbitrage_kwh, 2),
            "losses_kwh": round(losses_kwh, 2),
            "pv_forecast_kwh": round(pv_forecast_kwh, 2),
            "pv_compensation_factor": (
                round(pv_compensation_factor, 4)
                if pv_compensation_factor is not None
                else None
            ),
            "heat_pump_kwh": round(heat_pump_kwh, 2),
            "charge_current_a": round(charge_current, 1),
            "efficiency": round(efficiency, 1),
            "margin": margin,
            "start_hour": start_hour,
            "end_hour": end_hour,
            **(arbitrage_details or {}),
        }

    return DecisionOutcome(
        scenario=scenario,
        action_type="charge_scheduled",
        summary=summary,
        reason=reason,
        key_metrics=key_metrics,
        full_details=full_details,
    )
