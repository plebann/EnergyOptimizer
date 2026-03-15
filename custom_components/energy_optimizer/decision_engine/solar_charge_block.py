"""Solar charge blocking decision logic (pre-noon PV surplus check)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import Context
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR,
    CONF_DAYTIME_MIN_PRICE_SENSOR,
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_MIN_SOC,
    CONF_PRICE_SENSOR,
    CONF_WORK_MODE_ENTITY,
    DEFAULT_MIN_SOC,
    SUN_ABOVE_HORIZON,
    SUN_ENTITY,
    WORK_MODE_EXPORT_FIRST,
    WORK_MODE_ZERO_EXPORT_TO_LOAD,
)
from ..controllers.inverter import set_max_charge_current, set_program_soc, set_work_mode
from ..helpers import get_active_program_entity, get_float_state_info, get_required_float_state, resolve_daytime_min_price_time
from ..utils.forecast import get_pv_forecast_window
from .common import get_entry_data, get_required_current_soc_state, resolve_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_PRICE_BLOCK_FACTOR = 0.3

async def async_run_solar_charge_block(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
) -> None:
    """Check if morning PV surplus will overflow battery and block charging if so."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return
    config = entry.data

    max_charge_entity = config.get(CONF_MAX_CHARGE_CURRENT_ENTITY)
    max_charge_value, _max_charge_raw, max_charge_error = get_float_state_info(
        hass,
        max_charge_entity,
    )

    # Guard: only run while sun is above horizon
    sun_state = hass.states.get(SUN_ENTITY)
    if sun_state is None or sun_state.state != SUN_ABOVE_HORIZON:
        _LOGGER.debug("Solar charge block: sun not above horizon — skip")
        return

    now = dt_util.now()

    # When min price hour sensor is not configured, skip if charging is already blocked
    # (avoids redundant service calls)
    if max_charge_error is None and max_charge_value is not None and max_charge_value <= 0:
        _LOGGER.debug("Solar charge block: max charge current already 0 — skip")
        return

    # Min price hour check: restore or keep blocked based on whether the min-price window has passed
    if config.get(CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR):
        min_price_time = resolve_daytime_min_price_time(hass, config)
        if now.time() < min_price_time:
            # Before the min-price window — if charging is already blocked keep it that way
            if max_charge_value is not None and max_charge_value == 0:
                _LOGGER.debug(
                    "Solar charge block: before min price time %s, max charge already 0 — skip",
                    min_price_time,
                )
                return
        else:
            _LOGGER.debug(
                "Solar charge block: past min price time %s - no action needed",
                min_price_time,
            )
            return

    # Current price
    current_price = get_required_float_state(
        hass,
        config.get(CONF_PRICE_SENSOR),
        entity_name="Price sensor",
    )
    if current_price is None:
        return

    # Minimum daytime price — optional sensor; skip gracefully if not configured
    min_price_entity = config.get(CONF_DAYTIME_MIN_PRICE_SENSOR)
    if not min_price_entity:
        _LOGGER.debug("Solar charge block: daytime min price sensor not configured — skip")
        return

    min_price = get_required_float_state(
        hass,
        min_price_entity,
        entity_name="Daytime min price sensor",
    )
    if min_price is None:
        return

    if current_price <= 0:
        # If inverter is in Export First mode, switch to Zero Export to Load
        # and restore max charge current to full
        work_mode_entity = config.get(CONF_WORK_MODE_ENTITY)
        if work_mode_entity:
            wm_state = hass.states.get(str(work_mode_entity))
            if wm_state is not None and wm_state.state == WORK_MODE_EXPORT_FIRST:
                _LOGGER.info(
                    "Solar charge block: price %.4f zero or negative, switching %s from Export First to Zero Export to Load",
                    current_price,
                    work_mode_entity,
                )
                ctx = Context()
                await set_work_mode(
                    hass,
                    str(work_mode_entity),
                    WORK_MODE_ZERO_EXPORT_TO_LOAD,
                    entry=entry,
                    logger=_LOGGER,
                    context=ctx,
                )
                await set_max_charge_current(
                    hass,
                    max_charge_entity,
                    23,
                    entry=entry,
                    logger=_LOGGER,
                    context=ctx,
                )
                return
        return

    # Price gate: proceed only when current price is significantly above minimum
    _PRICE_MARGIN = max(100, _PRICE_BLOCK_FACTOR * current_price)  # Avoid blocking at very low prices
    if current_price - _PRICE_MARGIN < min_price:
        _LOGGER.debug(
            "Solar charge block: price gate skip — %.4f * %.4f = %.4f < min %.4f",
            _PRICE_BLOCK_FACTOR,
            current_price,
            _PRICE_BLOCK_FACTOR * current_price,
            min_price,
        )
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

    free_space_kwh = battery_space_sensor.native_value
    if free_space_kwh is None:
        _LOGGER.warning("Solar charge block: battery_space_sensor has no value — skip")
        return

    # Decision
    if pv_surplus_kwh <= free_space_kwh:
        _LOGGER.info(
            "Solar charge block: no action — PV surplus %.2f kWh <= free space %.2f kWh",
            pv_surplus_kwh,
            free_space_kwh,
        )
        return

    # Read current SOC to decide how to limit charging
    current_soc_state = get_required_current_soc_state(hass, config)
    if current_soc_state is None:
        _LOGGER.warning("Solar charge block: battery SOC unavailable — skip")
        return
    _, current_soc = current_soc_state
    min_soc = config.get(CONF_MIN_SOC, DEFAULT_MIN_SOC)

    if current_soc < min_soc:
        _LOGGER.info(
            "Solar charge block: BLOCKING (1A) — PV surplus %.2f kWh > free space %.2f kWh, "
            "SOC %.1f%% < min_soc %.1f%% (price %.4f, min %.4f, sunset %02d:00)",
            pv_surplus_kwh,
            free_space_kwh,
            current_soc,
            min_soc,
            current_price,
            min_price,
            sunset_hour,
        )
        await set_max_charge_current(
            hass,
            max_charge_entity,
            1,
            entry=entry,
            logger=_LOGGER,
            context=Context(),
        )
    else:
        # SOC >= min_soc: unblock charging but switch to Export First with target SOC locked
        # at current SOC so the inverter exports PV surplus instead of charging the battery
        prog_soc_entity = get_active_program_entity(hass, config, now)
        _LOGGER.info(
            "Solar charge block: EXPORT FIRST — PV surplus %.2f kWh > free space %.2f kWh, "
            "SOC %.1f%% >= min_soc %.1f%%, target SOC locked at %.1f%% "
            "(price %.4f, min %.4f, sunset %02d:00)",
            pv_surplus_kwh,
            free_space_kwh,
            current_soc,
            min_soc,
            current_soc,
            current_price,
            min_price,
            sunset_hour,
        )
        ctx = Context()
        await set_max_charge_current(
            hass,
            max_charge_entity,
            23,
            entry=entry,
            logger=_LOGGER,
            context=ctx,
        )
        await set_work_mode(
            hass,
            config.get(CONF_WORK_MODE_ENTITY),
            WORK_MODE_EXPORT_FIRST,
            entry=entry,
            logger=_LOGGER,
            context=ctx,
        )
        if prog_soc_entity:
            await set_program_soc(
                hass,
                prog_soc_entity,
                current_soc,
                entry=entry,
                logger=_LOGGER,
                context=ctx,
            )
        else:
            _LOGGER.debug("Solar charge block: no active program SOC entity — target SOC not set")
