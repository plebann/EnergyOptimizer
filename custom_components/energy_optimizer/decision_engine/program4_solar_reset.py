"""Program 4 solar-surplus reset decision logic."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..calculations.energy import calculate_losses
from ..calculations.utils import build_hourly_usage_array
from ..const import (
    CONF_BATTERY_SOC_SENSOR,
    CONF_DAILY_LOAD_SENSOR,
    CONF_ENABLE_HEAT_PUMP,
    CONF_PV_FORECAST_TODAY,
)
from ..controllers.inverter import set_program_soc
from ..helpers import (
    get_required_float_state,
    resolve_day_buy_window_start_hour,
    resolve_prog4_start_time,
    resolve_tariff_start_hour,
)
from ..utils.decision_dump import active_decision_audit, emit_decision_dump
from ..utils.forecast import get_heat_pump_forecast_window, get_pv_forecast_window
from .common import (
    get_battery_config,
    get_required_prog4_soc_state,
    resolve_entry,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _has_configured_pv_forecast(
    hass: HomeAssistant,
    config: dict[str, Any],
) -> bool:
    """Return whether the today PV forecast exposes detailed hourly data."""
    entity_id = config.get(CONF_PV_FORECAST_TODAY)
    state = hass.states.get(str(entity_id)) if entity_id else None
    attributes = getattr(state, "attributes", {}) if state is not None else {}
    return isinstance(attributes, dict) and isinstance(
        attributes.get("detailedHourly") or attributes.get("detailedForecast"),
        list,
    )


async def _async_run_program4_solar_reset(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
) -> None:
    """Reset Program 4 target when its pre-charge window has solar surplus."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    config = entry.data

    prog4_start = resolve_prog4_start_time(hass, config)
    if prog4_start is None:
        return

    tariff_start_hour = resolve_tariff_start_hour(hass, config)
    afternoon_charge_hour = resolve_day_buy_window_start_hour(
        hass,
        config,
        entry_id=entry.entry_id,
        default_hour=(tariff_start_hour - 2) % 24,
    )
    if prog4_start.hour >= afternoon_charge_hour:
        _LOGGER.debug(
            "Skipping Program 4 solar reset: start hour %02d is not before afternoon charge hour %02d",
            prog4_start.hour,
            afternoon_charge_hour,
        )
        return

    prog4_state = get_required_prog4_soc_state(hass, config)
    battery_soc = get_required_float_state(
        hass,
        config.get(CONF_BATTERY_SOC_SENSOR),
        entity_name="Battery SOC sensor",
    )
    daily_load = get_required_float_state(
        hass,
        config.get(CONF_DAILY_LOAD_SENSOR),
        entity_name="Daily load sensor",
    )
    if prog4_state is None or battery_soc is None or daily_load is None:
        return
    if not _has_configured_pv_forecast(hass, config):
        _LOGGER.warning("Skipping Program 4 solar reset: PV forecast is unavailable")
        return

    end_hour = afternoon_charge_hour
    hourly_usage = build_hourly_usage_array(
        config,
        hass.states.get,
        daily_load_fallback=daily_load,
    )
    usage_kwh = sum(hourly_usage[hour] for hour in range(prog4_start.hour, end_hour))
    pv_kwh, _ = get_pv_forecast_window(
        hass,
        config,
        start_hour=prog4_start.hour,
        end_hour=end_hour,
        apply_efficiency=False,
        compensate=False,
        entry_id=entry.entry_id,
    )
    heat_pump_kwh = 0.0
    if config.get(CONF_ENABLE_HEAT_PUMP):
        heat_pump_kwh, heat_pump_hourly = await get_heat_pump_forecast_window(
            hass,
            config,
            start_hour=prog4_start.hour,
            end_hour=end_hour,
        )
        if not heat_pump_hourly:
            _LOGGER.warning(
                "Skipping Program 4 solar reset: heat pump forecast is unavailable"
            )
            return

    _, losses_kwh = calculate_losses(
        hass,
        config,
        hours=end_hour - prog4_start.hour,
    )
    surplus_kwh = pv_kwh - usage_kwh - heat_pump_kwh - losses_kwh
    if surplus_kwh <= 0.0:
        _LOGGER.debug(
            "Skipping Program 4 solar reset: forecast surplus %.2f kWh is not positive",
            surplus_kwh,
        )
        return

    prog4_entity, current_prog4_soc = prog4_state
    target_soc = min(battery_soc, get_battery_config(config).min_soc_pv)
    if abs(target_soc - current_prog4_soc) <= 0.01:
        _LOGGER.debug("Program 4 SOC already matches solar reset target %.0f%%", target_soc)
        return

    await set_program_soc(
        hass,
        prog4_entity,
        target_soc,
        entry=entry,
        logger=_LOGGER,
    )
    _LOGGER.info(
        "Reset Program 4 SOC to %.0f%%: forecast surplus %.2f kWh from %02d:00 to %02d:00",
        target_soc,
        surplus_kwh,
        prog4_start.hour,
        end_hour,
    )


async def async_run_program4_solar_reset(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    trigger: str = "manual:program4_solar_reset",
) -> None:
    """Run Program 4 reset and dump a completed inverter decision."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    async with active_decision_audit(hass, entry, trigger=trigger) as audit:
        await _async_run_program4_solar_reset(hass, entry_id=entry_id)
        if not audit.actions:
            return
        emit_decision_dump(
            _LOGGER,
            audit,
            {
                "scenario": "Program 4 solar reset",
                "action_type": "program_soc_updated",
                "summary": "Reset Program 4 SOC from solar surplus",
                "reason": "forecast_surplus_positive",
                "details": {},
            },
        )
