"""Heat pump forecast helpers for Energy Optimizer."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.util import dt as dt_util

from ..const import (
    CONF_ENABLE_HEAT_PUMP,
    CONF_HEAT_PUMP_FORECAST_DOMAIN,
    CONF_HEAT_PUMP_FORECAST_SERVICE,
    DEFAULT_HEAT_PUMP_FORECAST_DOMAIN,
    DEFAULT_HEAT_PUMP_FORECAST_SERVICE,
)
from .time_window import build_hour_window

_LOGGER = logging.getLogger(__name__)


def _get_service_config(config: dict[str, Any]) -> tuple[str, str]:
    """Resolve heat pump forecast service domain and name."""
    domain = config.get(
        CONF_HEAT_PUMP_FORECAST_DOMAIN, DEFAULT_HEAT_PUMP_FORECAST_DOMAIN
    )
    service = config.get(
        CONF_HEAT_PUMP_FORECAST_SERVICE, DEFAULT_HEAT_PUMP_FORECAST_SERVICE
    )
    return domain, service

async def get_heat_pump_forecast(
    hass: Any, config: dict[str, Any], *, starting_hour: int, hours_ahead: int
) -> tuple[float, dict[int, float]]:
    """Fetch heat pump forecast with per-hour energy breakdown.

    Returns (total_kwh, hourly_kwh). Falls back to (0.0, {}) on errors.
    """
    if not config.get(CONF_ENABLE_HEAT_PUMP):
        _LOGGER.debug("Heat pump integration disabled, skipping forecast")
        return 0.0, {}

    domain, service = _get_service_config(config)
    if not hass.services.has_service(domain, service):
        _LOGGER.warning(
            "Heat pump forecast service not available: %s.%s",
            domain,
            service,
        )
        return 0.0, {}

    try:
        response = await hass.services.async_call(
            domain,
            service,
            {
                "starting_hour": starting_hour,
                "hours_ahead": hours_ahead,
            },
            blocking=True,
            return_response=True,
        )
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Heat pump forecast failed: %s", exc)
        return 0.0, {}
    _LOGGER.debug("Heat pump forecast response: %s", response)

    if not isinstance(response, dict):
        return 0.0, {}

    total_kwh = float(response.get("total_energy_kwh", 0.0) or 0.0)
    window_hours = set(build_hour_window(starting_hour, (starting_hour + hours_ahead) % 24))
    hourly_kwh: dict[int, float] = {}
    hours_list = response.get("hours")
    if isinstance(hours_list, list):
        for item in hours_list:
            if not isinstance(item, dict):
                continue
            dt_value = item.get("datetime")
            energy_value = item.get("energy_kwh")
            if dt_value is None or energy_value is None:
                continue
            dt_parsed = dt_util.parse_datetime(str(dt_value))
            if dt_parsed is None:
                continue
            hour = dt_parsed.hour
            if hour not in window_hours:
                continue
            try:
                hourly_kwh[hour] = hourly_kwh.get(hour, 0.0) + float(energy_value)
            except (ValueError, TypeError):
                continue

    return total_kwh, hourly_kwh
