"""Daytime export blocking based on price and forecasted surplus."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import Context
from homeassistant.util import dt as dt_util

from ..calculations.battery import calculate_hourly_charge_capacity
from ..calculations.utils import build_hourly_usage_array
from ..const import (
    CONF_BATTERY_SOC_SENSOR,
    CONF_BEV_CHARGING_BINARY_SENSOR,
    CONF_BEV_CHARGING_POWER_SENSOR,
    CONF_INVERTER_EXPORT_SURPLUS_SWITCH,
    CONF_INVERTER_OFFGRID_SWITCH,
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_PRICE_SENSOR,
    CONF_PV_FORECAST_TODAY,
    CONF_SELL_PRICE_SENSOR,
    DOMAIN,
    SUN_ABOVE_HORIZON,
    SUN_ENTITY,
)
from ..controllers.inverter import turn_off_switch, turn_on_switch
from ..helpers import get_float_state_info, get_required_float_state
from ..utils.forecast import get_pv_forecast_window
from .common import get_battery_config, resolve_entry

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_LOAD_USAGE_KEYS = (
    "load_usage_00_04",
    "load_usage_04_08",
    "load_usage_08_12",
    "load_usage_12_16",
    "load_usage_16_20",
    "load_usage_20_24",
)


def _decision(reason: str, **details: Any) -> dict[str, Any]:
    """Build a structured export-block decision for diagnostics."""
    return {"reason": reason, "timestamp": dt_util.now().isoformat(), **details}


def _get_offgrid_threshold(hass: HomeAssistant, entry_id: str) -> float:
    """Read the configured off-grid threshold from the integration number."""
    threshold_number = (
        hass.data.get(DOMAIN, {})
        .get(entry_id, {})
        .get("export_block_offgrid_threshold")
    )
    try:
        return float(threshold_number.native_value)
    except (AttributeError, TypeError, ValueError):
        _LOGGER.warning(
            "Export block control: threshold number unavailable; using its default value"
        )
        return 3.5


def _get_hourly_load_kwh(
    hass: HomeAssistant,
    config: dict[str, Any],
    hour: int,
) -> float | None:
    """Return the configured hourly load forecast or None when it is unavailable."""
    load_key = _LOAD_USAGE_KEYS[hour // 4]
    load_entity = config.get(load_key)
    if not load_entity:
        _LOGGER.warning(
            "Export block control: %s is not configured; cannot calculate surplus",
            load_key,
        )
        return None

    load_kwh, _, error = get_float_state_info(hass, str(load_entity))
    if error is not None or load_kwh is None:
        _LOGGER.warning(
            "Export block control: load sensor %s is unavailable (%s)",
            load_entity,
            error,
        )
        return None

    return build_hourly_usage_array(config, hass.states.get, daily_load_fallback=None)[hour]


def _get_battery_hourly_capacity_kwh(
    hass: HomeAssistant,
    config: dict[str, Any],
) -> float | None:
    """Return energy the battery can accept within one hour."""
    soc_entity = config.get(CONF_BATTERY_SOC_SENSOR)
    if not soc_entity:
        _LOGGER.warning("Export block control: battery SOC sensor not configured")
        return None

    current_soc = get_required_float_state(
        hass,
        str(soc_entity),
        entity_name="Battery SOC sensor",
    )
    if current_soc is None:
        return None

    battery_config = get_battery_config(config)
    max_charge_entity = config.get(CONF_MAX_CHARGE_CURRENT_ENTITY)
    max_current_a: float | None = None
    if max_charge_entity:
        max_current_a, _, error = get_float_state_info(hass, str(max_charge_entity))
        if error is not None or max_current_a is None:
            _LOGGER.warning(
                "Export block control: max charge current entity %s is unavailable (%s)",
                max_charge_entity,
                error,
            )
            return None
    return calculate_hourly_charge_capacity(
        current_soc,
        battery_config.max_soc,
        battery_config.capacity_ah,
        battery_config.voltage,
        max_current_a=max_current_a,
    )


def _get_bev_state_and_power_kwh(
    hass: HomeAssistant,
    config: dict[str, Any],
) -> tuple[bool, float] | None:
    """Return whether BEV charging is active and its hourly energy consumption."""
    bev_state_entity = config.get(CONF_BEV_CHARGING_BINARY_SENSOR)
    if not bev_state_entity:
        return False, 0.0

    bev_state = hass.states.get(str(bev_state_entity))
    if bev_state is None or bev_state.state in {"unknown", "unavailable"}:
        _LOGGER.warning(
            "Export block control: BEV charging sensor %s is unavailable",
            bev_state_entity,
        )
        return None

    is_charging = bev_state.state == "on"
    if not is_charging:
        return False, 0.0

    bev_power_entity = config.get(CONF_BEV_CHARGING_POWER_SENSOR)
    if not bev_power_entity:
        return True, 0.0

    bev_power_w, _, error = get_float_state_info(hass, str(bev_power_entity))
    if error is not None or bev_power_w is None:
        _LOGGER.warning(
            "Export block control: BEV power sensor %s is unavailable (%s)",
            bev_power_entity,
            error,
        )
        return None

    return True, max(bev_power_w, 0.0) / 1000.0


def _get_current_hour_pv_kwh(
    hass: HomeAssistant,
    config: dict[str, Any],
    entry_id: str,
    hour: int,
) -> float | None:
    """Return compensated PV forecast for the current hour."""
    pv_entity = config.get(CONF_PV_FORECAST_TODAY)
    pv_state = hass.states.get(str(pv_entity)) if pv_entity else None
    detailed_forecast = (
        pv_state.attributes.get("detailedHourly")
        if pv_state is not None
        else None
    )
    if not isinstance(detailed_forecast, list):
        detailed_forecast = (
            pv_state.attributes.get("detailedForecast")
            if pv_state is not None
            else None
        )
    if not isinstance(detailed_forecast, list) or not detailed_forecast:
        _LOGGER.warning(
            "Export block control: current-day detailed PV forecast is unavailable"
        )
        return None

    next_hour = (hour + 1) % 24
    pv_kwh, _ = get_pv_forecast_window(
        hass,
        config,
        start_hour=hour,
        end_hour=next_hour,
        apply_efficiency=True,
        compensate=True,
        entry_id=entry_id,
    )
    return pv_kwh


async def _set_switch_state(
    hass: HomeAssistant,
    entry: ConfigEntry,
    entity_id: str | None,
    *,
    turn_on: bool,
) -> bool:
    """Set a switch only when its known state differs from the requested state."""
    if not entity_id:
        return False
    switch_state = hass.states.get(str(entity_id))
    if switch_state is None or switch_state.state in {"unknown", "unavailable"}:
        _LOGGER.warning(
            "Export block control: switch entity %s is unavailable", entity_id
        )
        return False

    is_on = switch_state.state == "on"
    if is_on == turn_on:
        return False

    if turn_on:
        await turn_on_switch(
            hass,
            str(entity_id),
            entry=entry,
            logger=_LOGGER,
            context=Context(),
        )
    else:
        await turn_off_switch(
            hass,
            str(entity_id),
            entry=entry,
            logger=_LOGGER,
            context=Context(),
        )
    return True


async def _restore_normal_operation(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Reconnect to the grid before enabling export."""
    config = entry.data
    await _set_switch_state(
        hass,
        entry,
        config.get(CONF_INVERTER_OFFGRID_SWITCH),
        turn_on=False,
    )
    await _set_switch_state(
        hass,
        entry,
        config.get(CONF_INVERTER_EXPORT_SURPLUS_SWITCH),
        turn_on=True,
    )


async def _block_export_with_grid(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Keep grid access while blocking the configured export surplus switch."""
    config = entry.data
    await _set_switch_state(
        hass,
        entry,
        config.get(CONF_INVERTER_EXPORT_SURPLUS_SWITCH),
        turn_on=False,
    )
    await _set_switch_state(
        hass,
        entry,
        config.get(CONF_INVERTER_OFFGRID_SWITCH),
        turn_on=False,
    )


async def _block_export_offgrid(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Disable export before disconnecting the inverter from the grid."""
    config = entry.data
    await _set_switch_state(
        hass,
        entry,
        config.get(CONF_INVERTER_EXPORT_SURPLUS_SWITCH),
        turn_on=False,
    )
    await _set_switch_state(
        hass,
        entry,
        config.get(CONF_INVERTER_OFFGRID_SWITCH),
        turn_on=True,
    )


async def async_restore_export_block_control(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
) -> dict[str, Any] | None:
    """Restore grid and export after the daylight export-control window ends."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return None
    await _restore_normal_operation(hass, entry)
    return _decision("sunset_restore", action="normal_operation")


def _can_enter_offgrid(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Return whether both switches required for safe off-grid entry are available."""
    config = entry.data
    export_switch = config.get(CONF_INVERTER_EXPORT_SURPLUS_SWITCH)
    offgrid_switch = config.get(CONF_INVERTER_OFFGRID_SWITCH)
    if not export_switch or not offgrid_switch:
        return False

    for switch_entity in (export_switch, offgrid_switch):
        state = hass.states.get(str(switch_entity))
        if state is None or state.state in {"unknown", "unavailable"}:
            return False
    return True


async def async_run_export_block_control(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
) -> dict[str, Any] | None:
    """Control export safely from sell price and the current-hour energy balance."""
    entry = resolve_entry(hass, entry_id)
    if entry is None:
        return None

    sun_state = hass.states.get(SUN_ENTITY)
    if sun_state is None or sun_state.state != SUN_ABOVE_HORIZON:
        return _decision("sun_not_above_horizon")

    config = entry.data
    price_entity = config.get(CONF_SELL_PRICE_SENSOR) or config.get(CONF_PRICE_SENSOR)
    if not price_entity:
        _LOGGER.warning("Export block control: no sell price sensor configured")
        return _decision("missing_sell_price_sensor")

    price = get_required_float_state(
        hass,
        str(price_entity),
        entity_name=(
            "Sell price sensor"
            if config.get(CONF_SELL_PRICE_SENSOR)
            else "Price sensor"
        ),
    )
    if price is None:
        await _restore_normal_operation(hass, entry)
        return _decision("missing_sell_price", action="normal_operation")

    if round(price, 1) > 0:
        await _restore_normal_operation(hass, entry)
        return _decision(
            "positive_sell_price",
            action="normal_operation",
            sell_price=round(price, 2),
        )

    now = dt_util.now()
    hourly_load_kwh = _get_hourly_load_kwh(hass, config, now.hour)
    battery_capacity_kwh = _get_battery_hourly_capacity_kwh(hass, config)
    bev_data = _get_bev_state_and_power_kwh(hass, config)
    pv_kwh = _get_current_hour_pv_kwh(hass, config, entry.entry_id, now.hour)
    if (
        hourly_load_kwh is None
        or battery_capacity_kwh is None
        or bev_data is None
        or pv_kwh is None
    ):
        await _restore_normal_operation(hass, entry)
        return _decision(
            "incomplete_energy_balance",
            action="normal_operation",
            sell_price=round(price, 2),
        )

    bev_charging, bev_kwh = bev_data
    surplus_kwh = max(0.0, pv_kwh - hourly_load_kwh - battery_capacity_kwh - bev_kwh)
    threshold_kwh = _get_offgrid_threshold(hass, entry.entry_id)
    details = {
        "sell_price": round(price, 2),
        "pv_forecast_kwh": round(pv_kwh, 3),
        "load_forecast_kwh": round(hourly_load_kwh, 3),
        "battery_hourly_capacity_kwh": round(battery_capacity_kwh, 3),
        "bev_charging": bev_charging,
        "bev_charging_kwh": round(bev_kwh, 3),
        "forecast_export_surplus_kwh": round(surplus_kwh, 3),
        "offgrid_threshold_kwh": round(threshold_kwh, 3),
    }

    if bev_charging and surplus_kwh <= threshold_kwh:
        await _restore_normal_operation(hass, entry)
        return _decision(
            "bev_absorbs_surplus",
            action="normal_operation",
            **details,
        )

    if not bev_charging and surplus_kwh > threshold_kwh and _can_enter_offgrid(hass, entry):
        await _block_export_offgrid(hass, entry)
        return _decision(
            "surplus_above_offgrid_threshold",
            action="block_export_offgrid",
            **details,
        )

    await _block_export_with_grid(hass, entry)
    return _decision(
        (
            "offgrid_path_unavailable"
            if not bev_charging and surplus_kwh > threshold_kwh
            else "block_export_with_grid"
        ),
        action="block_export_with_grid",
        **details,
    )
