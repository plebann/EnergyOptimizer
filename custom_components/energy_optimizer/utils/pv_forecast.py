"""PV forecast utilities."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from ..const import (
    CONF_PV_EFFICIENCY,
    CONF_PV_FORECAST_REMAINING,
    CONF_PV_FORECAST_TODAY,
    CONF_PV_FORECAST_TOMORROW,
    CONF_PV_PRODUCTION_SENSOR,
    DEFAULT_PV_EFFICIENCY,
    DOMAIN,
)
from .time_window import build_hour_window

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
    entry_id: str | None = None,
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

    forecast_adjusted, factor_today, reason = _calculate_forecast_adjustment(
        today_kwh,
        remaining_kwh,
        production_kwh,
    )
    if reason is not None or factor_today is None:
        return None, reason

    factor_sensor = _get_sensor_compensation_factor(hass, entry_id)
    factor_combined = _combine_compensation_factors(factor_today, factor_sensor)
    if factor_combined is None:
        return None, "missing_compensation"

    forecast_adjusted = today_kwh * factor_combined
    return forecast_adjusted, None


def get_pv_forecast(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    start_hour: int,
    end_hour: int,
    apply_efficiency: bool = True,
    compensate: bool = False,
    entry_id: str | None = None,
) -> dict[int, float]:
    """Return PV forecast energy per hour between start and end hour."""
    hourly_kwh = _collect_pv_forecast_hourly_kwh(
        hass, config, start_hour=start_hour, end_hour=end_hour
    )

    if compensate:
        hourly_kwh = _apply_pv_compensation(
            hass,
            config,
            hourly_kwh,
            start_hour=start_hour,
            end_hour=end_hour,
            entry_id=entry_id,
        )

    if apply_efficiency:
        hourly_kwh = _apply_pv_efficiency(config, hourly_kwh)

    return sum(hourly_kwh.values()), hourly_kwh


def get_pv_compensation_factor(
    hass: HomeAssistant, entry_id: str | None
) -> float | None:
    """Return the PV compensation factor from the integration sensor."""
    return _get_sensor_compensation_factor(hass, entry_id)


def _collect_pv_forecast_hourly_kwh(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    start_hour: int,
    end_hour: int,
) -> dict[int, float]:
    """Collect PV forecast energy per hour without efficiency adjustments."""
    hour_window = build_hour_window(start_hour, end_hour)
    hourly_kwh: dict[int, float] = {hour: 0.0 for hour in hour_window}
    now_hour = dt_util.now().hour
    today_sensor = config.get(CONF_PV_FORECAST_TODAY)
    tomorrow_sensor = config.get(CONF_PV_FORECAST_TOMORROW)
    segments: list[tuple[list[dict], int, int]] = []

    if start_hour < now_hour:
        if end_hour < start_hour:
            _LOGGER.error(
                "Invalid PV forecast window: end_hour %s < start_hour %s for tomorrow",
                end_hour,
                start_hour,
            )
            return hourly_kwh
        detailed = _get_detailed_forecast(hass, tomorrow_sensor, "tomorrow")
        if detailed:
            segments.append((detailed, start_hour, end_hour))
    elif end_hour > start_hour:
        detailed = _get_detailed_forecast(hass, today_sensor, "today")
        if detailed:
            segments.append((detailed, start_hour, end_hour))
    else:
        detailed_today = _get_detailed_forecast(hass, today_sensor, "today")
        if detailed_today:
            segments.append((detailed_today, start_hour, 24))
        detailed_tomorrow = _get_detailed_forecast(hass, tomorrow_sensor, "tomorrow")
        if detailed_tomorrow:
            segments.append((detailed_tomorrow, 0, end_hour))

    if not segments:
        return hourly_kwh

    for detailed, window_start, window_end in segments:
        for item in detailed:
            if not isinstance(item, dict):
                continue
            period_start = item.get("period_start")
            pv_estimate = item.get("pv_estimate")
            if period_start is None or pv_estimate is None:
                continue
            dt_value = dt_util.parse_datetime(str(period_start))
            if dt_value is None:
                continue
            if window_start <= dt_value.hour < window_end:
                try:
                    hourly_kwh[dt_value.hour] += float(pv_estimate)
                except (ValueError, TypeError):
                    continue

    return hourly_kwh


def _get_detailed_forecast(
    hass: HomeAssistant, sensor: str | None, label: str
) -> list[dict] | None:
    if not sensor:
        _LOGGER.warning("PV forecast %s sensor not configured", label)
        return None
    pv_state = hass.states.get(sensor)
    if pv_state is None:
        _LOGGER.warning("PV forecast %s sensor %s unavailable", label, sensor)
        return None
    detailed = pv_state.attributes.get("detailedHourly")
    if not isinstance(detailed, list):
        detailed = pv_state.attributes.get("detailedForecast")
    if not isinstance(detailed, list):
        _LOGGER.warning(
            "PV forecast %s sensor has no detailedHourly/detailedForecast: %s",
            label,
            sensor,
        )
        return None
    return detailed


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
    entry_id: str | None = None,
) -> dict[int, float]:
    today_kwh, remaining_kwh, production_kwh, reason = _get_forecast_inputs(
        hass, config
    )
    if reason is not None:
        return hourly_kwh

    _forecast_adjusted, factor_today, reason = _calculate_forecast_adjustment(
        today_kwh,
        remaining_kwh,
        production_kwh,
    )
    if reason is not None or factor_today is None:
        return hourly_kwh

    factor_sensor = _get_sensor_compensation_factor(hass, entry_id)
    factor_combined = _combine_compensation_factors(factor_today, factor_sensor)
    if factor_combined is None:
        return hourly_kwh

    factor_combined = min(factor_combined, 1.5)
    return {hour: value * factor_combined for hour, value in hourly_kwh.items()}


def _combine_compensation_factors(
    factor_today: float | None, factor_sensor: float | None
) -> float | None:
    if factor_today is None and factor_sensor is None:
        return None
    if factor_today is None:
        return factor_sensor
    if factor_sensor is None:
        return factor_today
    return (factor_today + factor_sensor) / 2.0


def _get_sensor_compensation_factor(
    hass: HomeAssistant, entry_id: str | None
) -> float | None:
    if entry_id is None:
        return None
    if DOMAIN not in hass.data or entry_id not in hass.data[DOMAIN]:
        return None
    sensor = hass.data[DOMAIN][entry_id].get("pv_forecast_compensation_sensor")
    if sensor is None:
        return None
    value = getattr(sensor, "native_value", None)
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


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
