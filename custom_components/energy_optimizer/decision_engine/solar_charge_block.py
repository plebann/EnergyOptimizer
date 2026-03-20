"""Solar charge blocking decision logic (pre-noon PV surplus check)."""
from __future__ import annotations

from datetime import time
import logging
from typing import TYPE_CHECKING

from homeassistant.core import Context
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR,
    CONF_DAYTIME_MIN_PRICE_SENSOR,
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_MIN_SOC_PV,
    CONF_PRICE_SENSOR,
    CONF_WORK_MODE_ENTITY,
    DEFAULT_MIN_SOC_PV,
    SUN_ABOVE_HORIZON,
    SUN_ENTITY,
    WORK_MODE_EXPORT_FIRST,
    WORK_MODE_ZERO_EXPORT_TO_LOAD,
)
from ..controllers.inverter import set_max_charge_current, set_program_soc, set_work_mode
from ..helpers import (
    get_active_program_entity,
    get_required_float_state,
    resolve_daytime_min_price_time,
    resolve_morning_max_price_hour,
)
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

    # Guard: only run while sun is above horizon
    sun_state = hass.states.get(SUN_ENTITY)
    if sun_state is None or sun_state.state != SUN_ABOVE_HORIZON:
        _LOGGER.debug("Solar charge block: sun not above horizon — skip")
        return

    now = dt_util.now()

    morning_max_price_hour = resolve_morning_max_price_hour(
        hass,
        config,
        default_hour=7,
    )
    morning_max_price_time = time(morning_max_price_hour, 0)
    if now.time() < morning_max_price_time:
        _LOGGER.debug(
            "Solar charge block: current time %s is before morning max price time %s — skip",
            now.time(),
            morning_max_price_time,
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

    min_price_hour_entity = config.get(CONF_DAYTIME_MIN_PRICE_HOUR_SENSOR)
    if not min_price_hour_entity:
        _LOGGER.debug(
            "Solar charge block: daytime min price hour sensor not configured — skip"
        )
        return

    min_price_time = resolve_daytime_min_price_time(hass, config)
    if now.time() >= min_price_time:
        _LOGGER.debug(
            "Solar charge block: current time %s is at or past min price time %s — skip",
            now.time(),
            min_price_time,
        )
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

    pv_surplus_current_hour_kwh, _ = get_pv_forecast_window(
        hass,
        config,
        start_hour=now.hour,
        end_hour=now.hour + 1,
        apply_efficiency=True,
    )
    if pv_surplus_current_hour_kwh <= 0:
        _LOGGER.info(
            "Solar charge block: no action — current hour PV forecast %.2f kWh <= 0",
            pv_surplus_current_hour_kwh,
        )
        return

    # Read current SOC to decide how to limit charging
    current_soc_state = get_required_current_soc_state(hass, config)
    if current_soc_state is None:
        _LOGGER.warning("Solar charge block: battery SOC unavailable — skip")
        return
    _, current_soc = current_soc_state
    min_soc_pv = float(config.get(CONF_MIN_SOC_PV, DEFAULT_MIN_SOC_PV))

    work_mode_entity = config.get(CONF_WORK_MODE_ENTITY)
    # Guard: when blocking already reached Export First state, wait for the
    # daytime minimum-price restore logic to revert settings.
    work_mode_state = hass.states.get(str(work_mode_entity))
    ctx = Context()
    prog_soc_entity = get_active_program_entity(hass, config, now)

    if current_soc <= min_soc_pv:
        _LOGGER.info(
            "Solar charge block: BLOCKING — PV surplus %.2f kWh > free space %.2f kWh, "
            "SOC %.1f%% <= min_soc_pv %.1f%% (price %.4f, min %.4f, sunset %02d:00)",
            pv_surplus_kwh,
            free_space_kwh,
            current_soc,
            min_soc_pv,
            current_price,
            min_price,
            sunset_hour,
        )
        await set_max_charge_current(
            hass,
            max_charge_entity,
            0,
            entry=entry,
            logger=_LOGGER,
            context=ctx,
        )
        await set_program_soc(
            hass,
            prog_soc_entity,
            11,
            entry=entry,
            logger=_LOGGER,
            context=ctx,
        )
        await set_work_mode(
            hass,
            config.get(CONF_WORK_MODE_ENTITY),
            WORK_MODE_ZERO_EXPORT_TO_LOAD,
            entry=entry,
            logger=_LOGGER,
            context=ctx,
        )
    else:
        if (work_mode_state.state == WORK_MODE_EXPORT_FIRST):
            _LOGGER.debug(
                "Solar charge block: work mode already Export First — skip"
            )
            return
        # SOC >= min_soc_pv: switch to Export First while
        # locking target SOC to min_soc_pv.
        _LOGGER.info(
            "Solar charge block: EXPORT FIRST — PV surplus %.2f kWh > free space %.2f kWh, "
            "SOC %.1f%% >= min_soc_pv %.1f%%, target SOC locked at %.1f%% "
            "(price %.4f, min %.4f, sunset %02d:00)",
            pv_surplus_kwh,
            free_space_kwh,
            current_soc,
            min_soc_pv,
            min_soc_pv,
            current_price,
            min_price,
            sunset_hour,
        )
        await set_work_mode(
            hass,
            config.get(CONF_WORK_MODE_ENTITY),
            WORK_MODE_EXPORT_FIRST,
            entry=entry,
            logger=_LOGGER,
            context=ctx,
        )
        await set_program_soc(
            hass,
            prog_soc_entity,
            min_soc_pv,
            entry=entry,
            logger=_LOGGER,
            context=ctx,
        )
