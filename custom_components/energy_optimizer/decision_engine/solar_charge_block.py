"""Solar charge blocking decision logic."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import Context
from homeassistant.util import dt as dt_util

from ..calculations.energy import calculate_losses, hourly_demand
from ..calculations.utils import build_hourly_usage_array
from ..const import (
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_PV_FORECAST_TODAY,
    DEFAULT_MAX_CHARGE_CURRENT,
    SUN_ABOVE_HORIZON,
    SUN_ENTITY,
)
from ..controllers.inverter import set_max_charge_current
from ..helpers import (
    get_float_state_info,
    resolve_daytime_min_price_time,
    resolve_morning_max_price_hour,
)
from ..utils.decision_dump import active_decision_audit, emit_decision_dump
from ..utils.forecast import get_heat_pump_forecast_window, get_pv_forecast_window
from .common import get_entry_data, resolve_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

async def _async_run_solar_charge_block(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
) -> None:
    """Block PV charging while morning export remains valuable."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    config = entry.data

    max_charge_entity = config.get(CONF_MAX_CHARGE_CURRENT_ENTITY)
    if not max_charge_entity:
        _LOGGER.warning(
            "Solar charge block: max charge current entity not configured — skip"
        )
        return

    now = dt_util.now()
    morning_sell_hour = resolve_morning_max_price_hour(
        hass,
        config,
        entry_id=entry.entry_id,
    )
    if now.hour < morning_sell_hour:
        _LOGGER.debug(
            "Solar charge block: before Morning Sell Window (%02d:00) — skip",
            morning_sell_hour,
        )
        return

    daytime_min_price_time = resolve_daytime_min_price_time(
        hass,
        config,
        entry_id=entry.entry_id,
    )
    if now.time() >= daytime_min_price_time:
        current_max_charge, raw_max_charge, max_charge_error = get_float_state_info(
            hass,
            str(max_charge_entity),
        )
        if max_charge_error is not None or current_max_charge != 0:
            _LOGGER.debug(
                "Solar charge block: after Midday Avoidance Window (%s) — skip "
                "(max charge current %s)",
                daytime_min_price_time.strftime("%H:%M"),
                raw_max_charge,
            )
            return

        _LOGGER.info(
            "Solar charge block: RESTORING — after Midday Avoidance Window (%s) "
            "and max charge current is 0",
            daytime_min_price_time.strftime("%H:%M"),
        )
        await set_max_charge_current(
            hass,
            max_charge_entity,
            DEFAULT_MAX_CHARGE_CURRENT,
            entry=entry,
            logger=_LOGGER,
            context=Context(),
        )
        return
    # Guard: only run while sun is above horizon
    sun_state = hass.states.get(SUN_ENTITY)
    if sun_state is None or sun_state.state != SUN_ABOVE_HORIZON:
        _LOGGER.debug("Solar charge block: sun not above horizon — skip")
        return

    # Determine sunset hour from sun entity attribute
    next_setting_raw = sun_state.attributes.get("next_setting")
    if next_setting_raw is None:
        _LOGGER.warning(
            "Solar charge block: %s missing next_setting attribute — skip",
            SUN_ENTITY,
        )
        return

    next_setting_dt = dt_util.parse_datetime(str(next_setting_raw))
    if next_setting_dt is None:
        _LOGGER.warning(
            "Solar charge block: cannot parse next_setting '%s' — skip",
            next_setting_raw,
        )
        return

    sunset_hour = dt_util.as_local(next_setting_dt).hour

    pv_forecast_entity = config.get(CONF_PV_FORECAST_TODAY)
    pv_forecast_state = (
        hass.states.get(str(pv_forecast_entity)) if pv_forecast_entity else None
    )
    pv_forecast_attributes = (
        getattr(pv_forecast_state, "attributes", {}) if pv_forecast_state else {}
    )
    detailed_forecast = pv_forecast_attributes.get("detailedHourly")
    if not isinstance(detailed_forecast, list):
        detailed_forecast = pv_forecast_attributes.get("detailedForecast")
    if not isinstance(detailed_forecast, list) or not detailed_forecast:
        _LOGGER.warning("Solar charge block: PV forecast unavailable — skip")
        return

    # PV surplus forecast from current hour until sunset
    pv_surplus_kwh, _ = get_pv_forecast_window(
        hass,
        config,
        start_hour=now.hour,
        end_hour=sunset_hour,
        apply_efficiency=True,
    )

    # Battery free space from integration sensor
    entry_data = get_entry_data(hass, entry.entry_id)
    battery_space_sensor = (
        entry_data.get("battery_space_sensor") if entry_data is not None else None
    )
    if battery_space_sensor is None:
        _LOGGER.warning("Solar charge block: battery_space_sensor unavailable — skip")
        return

    try:
        free_space_kwh = float(battery_space_sensor.native_value)
    except (TypeError, ValueError):
        _LOGGER.warning(
            "Solar charge block: battery_space_sensor has no valid value — skip"
        )
        return

    # Decision
    if pv_surplus_kwh <= free_space_kwh:
        _LOGGER.info(
            "Solar charge block: RESTORING — PV surplus %.2f kWh "
            "<= free space %.2f kWh",
            pv_surplus_kwh,
            free_space_kwh,
        )
        await set_max_charge_current(
            hass,
            max_charge_entity,
            DEFAULT_MAX_CHARGE_CURRENT,
            entry=entry,
            logger=_LOGGER,
            context=Context(),
        )
        return

    pv_production_current_hour_kwh, _ = get_pv_forecast_window(
        hass,
        config,
        start_hour=now.hour,
        end_hour=now.hour + 1,
        apply_efficiency=True,
    )
    hourly_usage = build_hourly_usage_array(
        config,
        hass.states.get,
        daily_load_fallback=None,
    )
    _, heat_pump_hourly = await get_heat_pump_forecast_window(
        hass,
        config,
        start_hour=now.hour,
        end_hour=now.hour + 1,
    )
    losses_hourly, _ = calculate_losses(hass, config, hours=1)
    current_hour_required_kwh = hourly_demand(
        now.hour,
        hourly_usage=hourly_usage,
        heat_pump_hourly=heat_pump_hourly,
        losses_hourly=losses_hourly,
        margin=1.1,
    )
    if pv_production_current_hour_kwh <= current_hour_required_kwh:
        _LOGGER.info(
            "Solar charge block: RESTORING — current hour PV forecast %.2f kWh "
            "<= current hour demand %.2f kWh",
            pv_production_current_hour_kwh,
            current_hour_required_kwh,
        )
        await set_max_charge_current(
            hass,
            max_charge_entity,
            DEFAULT_MAX_CHARGE_CURRENT,
            entry=entry,
            logger=_LOGGER,
            context=Context(),
        )
        return

    _LOGGER.info(
        "Solar charge block: BLOCKING — PV surplus %.2f kWh > free space %.2f kWh, "
        "current hour PV %.2f kWh > demand %.2f kWh (sunset %02d:00)",
        pv_surplus_kwh,
        free_space_kwh,
        pv_production_current_hour_kwh,
        current_hour_required_kwh,
        sunset_hour,
    )
    await set_max_charge_current(
        hass,
        max_charge_entity,
        0,
        entry=entry,
        logger=_LOGGER,
        context=Context(),
    )


async def async_run_solar_charge_block(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    trigger: str = "manual:solar_charge_block",
) -> None:
    """Run solar-charge control and dump a completed inverter decision."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    async with active_decision_audit(hass, entry, trigger=trigger) as audit:
        await _async_run_solar_charge_block(hass, entry_id=entry_id)
        if not audit.actions:
            return
        emit_decision_dump(
            _LOGGER,
            audit,
            {
                "scenario": "Solar charge block",
                "action_type": "charge_current_updated",
                "summary": "Updated maximum charge current",
                "reason": "solar_charge_block_evaluation",
                "details": {},
            },
        )
