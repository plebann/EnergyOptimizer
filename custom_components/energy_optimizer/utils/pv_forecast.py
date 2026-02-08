"""PV forecast utilities."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from ..const import (
    CONF_PV_EFFICIENCY,
    CONF_PV_FORECAST_SENSOR,
    CONF_PV_FORECAST_REMAINING,
    CONF_PV_FORECAST_TODAY,
    CONF_PV_PRODUCTION_SENSOR,
    DEFAULT_PV_EFFICIENCY,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def get_forecast_adjusted_kwh(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    pv_forecast_today_entity: str | None = None,
    pv_forecast_remaining_entity: str | None = None,
    pv_production_entity: str | None = None,
) -> tuple[float | None, str | None]:
    """Return adjusted PV forecast for today based on production progress."""
    today_kwh, remaining_kwh, production_kwh, reason = _get_forecast_inputs(
        hass,
        config,
        pv_forecast_today_entity=pv_forecast_today_entity,
        pv_forecast_remaining_entity=pv_forecast_remaining_entity,
        pv_production_entity=pv_production_entity,
    )
    if reason is not None:
        return None, reason

    forecast_adjusted, _factor, reason = _calculate_forecast_adjustment(
        today_kwh,
        remaining_kwh,
        production_kwh,
    )
    return forecast_adjusted, reason


def get_pv_forecast_kwh(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    start_hour: int = 6,
    end_hour: int,
    apply_efficiency: bool = True,
    compensate: bool = False,
) -> float:
    """Return PV forecast energy between start and end hour."""
    hourly_values = get_pv_forecast_hourly_kwh(
        hass,
        config,
        start_hour=start_hour,
        end_hour=end_hour,
        apply_efficiency=apply_efficiency,
        compensate=compensate,
    )
    return sum(hourly_values.values())


def get_pv_forecast_hourly_kwh(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    start_hour: int,
    end_hour: int,
    apply_efficiency: bool = True,
    compensate: bool = False,
) -> dict[int, float]:
    """Return PV forecast energy per hour between start and end hour."""
    hourly_kwh = _collect_pv_forecast_hourly_kwh(
        hass, config, start_hour=start_hour, end_hour=end_hour
    )

    if compensate:
        hourly_kwh = _apply_pv_compensation(
            hass, config, hourly_kwh, start_hour=start_hour, end_hour=end_hour
        )

    if apply_efficiency:
        hourly_kwh = _apply_pv_efficiency(config, hourly_kwh)

    return hourly_kwh


def _collect_pv_forecast_hourly_kwh(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    start_hour: int,
    end_hour: int,
) -> dict[int, float]:
    """Collect PV forecast energy per hour without efficiency adjustments."""
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

    return hourly_kwh


def _apply_pv_efficiency(
    config: dict[str, object], hourly_kwh: dict[int, float]
) -> dict[int, float]:
    pv_efficiency = config.get(CONF_PV_EFFICIENCY, DEFAULT_PV_EFFICIENCY)
    if pv_efficiency is None:
        return hourly_kwh

    try:
        efficiency = float(pv_efficiency)
    except (ValueError, TypeError):
        efficiency = DEFAULT_PV_EFFICIENCY

    return {hour: value * efficiency for hour, value in hourly_kwh.items()}


def _apply_pv_compensation(
    hass: HomeAssistant,
    config: dict[str, object],
    hourly_kwh: dict[int, float],
    *,
    start_hour: int,
    end_hour: int,
) -> dict[int, float]:
    today_kwh, remaining_kwh, production_kwh, reason = _get_forecast_inputs(
        hass, config
    )
    if reason is not None:
        return hourly_kwh

    _forecast_adjusted, factor, reason = _calculate_forecast_adjustment(
        today_kwh,
        remaining_kwh,
        production_kwh,
    )
    if reason is not None or factor is None:
        return hourly_kwh

    factor = min(factor, 1.5)
    return {hour: value * factor for hour, value in hourly_kwh.items()}


def _calculate_forecast_adjustment(
    today_kwh: float,
    remaining_kwh: float,
    production_kwh: float,
) -> tuple[float | None, float | None, str | None]:
    expected_kwh = today_kwh - remaining_kwh
    if expected_kwh <= 0:
        return None, None, "invalid_denominator"
    if production_kwh <= 0:
        return None, None, "invalid_production"
    factor = production_kwh / expected_kwh
    forecast_adjusted = today_kwh * factor
    return forecast_adjusted, factor, None


def _get_forecast_inputs(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    pv_forecast_today_entity: str | None = None,
    pv_forecast_remaining_entity: str | None = None,
    pv_production_entity: str | None = None,
) -> tuple[float | None, float | None, float | None, str | None]:
    remaining_sensor = pv_forecast_remaining_entity or config.get(
        CONF_PV_FORECAST_REMAINING
    )
    today_sensor = pv_forecast_today_entity or config.get(CONF_PV_FORECAST_TODAY)
    production_sensor = pv_production_entity or config.get(CONF_PV_PRODUCTION_SENSOR)
    if not remaining_sensor or not today_sensor or not production_sensor:
        return None, None, None, "missing_sensor"

    remaining_state = hass.states.get(remaining_sensor)
    if remaining_state is None:
        _LOGGER.warning("PV remaining forecast sensor %s unavailable", remaining_sensor)
        return None, None, None, "missing_remaining"

    today_state = hass.states.get(today_sensor)
    if today_state is None:
        _LOGGER.warning("PV forecast today sensor %s unavailable", today_sensor)
        return None, None, None, "missing_today"

    production_state = hass.states.get(production_sensor)
    if production_state is None:
        _LOGGER.warning("PV production sensor %s unavailable", production_sensor)
        return None, None, None, "missing_production"

    try:
        remaining_kwh = float(remaining_state.state)
    except (ValueError, TypeError):
        _LOGGER.warning(
            "PV remaining forecast sensor %s has invalid value: %s",
            remaining_sensor,
            remaining_state.state,
        )
        return None, None, None, "invalid_remaining"

    try:
        today_kwh = float(today_state.state)
    except (ValueError, TypeError):
        _LOGGER.warning(
            "PV forecast today sensor %s has invalid value: %s",
            today_sensor,
            today_state.state,
        )
        return None, None, None, "invalid_today"

    try:
        production_kwh = float(production_state.state)
    except (ValueError, TypeError):
        _LOGGER.warning(
            "PV production sensor %s has invalid value: %s",
            production_sensor,
            production_state.state,
        )
        return None, None, None, "invalid_production"

    return today_kwh, remaining_kwh, production_kwh, None
