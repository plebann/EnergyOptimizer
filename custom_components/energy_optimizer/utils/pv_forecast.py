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
    pv_forecast_kwh = 0.0
    pv_efficiency = config.get(CONF_PV_EFFICIENCY, DEFAULT_PV_EFFICIENCY)
    pv_sensor = config.get(CONF_PV_FORECAST_SENSOR) or config.get(
        CONF_PV_FORECAST_TODAY
    )
    if pv_sensor:
        pv_state = hass.states.get(pv_sensor)
        detailed_forecast = None
        if pv_state is not None:
            detailed_forecast = pv_state.attributes.get("detailedForecast")
        else:
            _LOGGER.warning("PV forecast sensor %s unavailable", pv_sensor)
        if isinstance(detailed_forecast, list):
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
                        pv_forecast_kwh += float(pv_estimate)
                    except (ValueError, TypeError):
                        continue
            pv_forecast_kwh *= float(pv_efficiency)
        else:
            _LOGGER.warning(
                "PV forecast sensor has no detailedForecast: %s", pv_sensor
            )
    else:
        _LOGGER.warning("PV forecast sensor not configured")

    return pv_forecast_kwh
