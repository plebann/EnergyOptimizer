"""PV forecast utilities."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from ..const import (
    CONF_PV_EFFICIENCY,
    CONF_PV_FORECAST_SENSOR,
    CONF_PV_FORECAST_TODAY,
    DEFAULT_PV_EFFICIENCY,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def get_pv_forecast_kwh(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    start_hour: int = 6,
    end_hour: int,
) -> float:
    """Return PV forecast energy between start and end hour."""
    hourly_values = get_pv_forecast_hourly_kwh(
        hass, config, start_hour=start_hour, end_hour=end_hour
    )
    return sum(hourly_values.values())


def get_pv_forecast_hourly_kwh(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    start_hour: int = 6,
    end_hour: int,
) -> dict[int, float]:
    """Return PV forecast energy per hour between start and end hour."""
    pv_efficiency = config.get(CONF_PV_EFFICIENCY, DEFAULT_PV_EFFICIENCY)
    pv_sensor = config.get(CONF_PV_FORECAST_SENSOR) or config.get(
        CONF_PV_FORECAST_TODAY
    )
    hourly_kwh: dict[int, float] = {hour: 0.0 for hour in range(start_hour, end_hour)}

    if not pv_sensor:
        _LOGGER.warning("PV forecast sensor not configured")
        return hourly_kwh

    pv_state = hass.states.get(pv_sensor)
    if pv_state is None:
        _LOGGER.warning("PV forecast sensor %s unavailable", pv_sensor)
        return hourly_kwh

    detailed_forecast = pv_state.attributes.get("detailedHourly")
    if detailed_forecast is None:
        detailed_forecast = pv_state.attributes.get("detailedForecast")

    if not isinstance(detailed_forecast, list):
        _LOGGER.warning(
            "PV forecast sensor has no detailedHourly/detailedForecast: %s",
            pv_sensor,
        )
        return hourly_kwh

    for item in detailed_forecast:
        if not isinstance(item, dict):
            continue
        period_start = item.get("period_start")
        pv_estimate = item.get("pv_estimate")
        if period_start is None or pv_estimate is None:
            continue
        dt_value = dt_util.parse_datetime(str(period_start))
        if dt_value is None:
            continue
        dt_value = dt_util.as_local(dt_value)
        if start_hour <= dt_value.hour < end_hour:
            try:
                hourly_kwh[dt_value.hour] += float(pv_estimate)
            except (ValueError, TypeError):
                continue

    if pv_efficiency is not None:
        try:
            efficiency = float(pv_efficiency)
        except (ValueError, TypeError):
            efficiency = DEFAULT_PV_EFFICIENCY
        hourly_kwh = {hour: value * efficiency for hour, value in hourly_kwh.items()}

    return hourly_kwh
