"""Heat pump forecast helpers for Energy Optimizer."""
from __future__ import annotations

import logging
from typing import Any

from ..const import (
    CONF_ENABLE_HEAT_PUMP,
    CONF_HEAT_PUMP_FORECAST_DOMAIN,
    CONF_HEAT_PUMP_FORECAST_SERVICE,
    DEFAULT_HEAT_PUMP_FORECAST_DOMAIN,
    DEFAULT_HEAT_PUMP_FORECAST_SERVICE,
)

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


async def async_fetch_heat_pump_forecast(
    hass: Any, config: dict[str, Any], *, starting_hour: int, hours_ahead: int
) -> float:
    """Fetch heat pump forecast energy usage in kWh.

    Returns 0.0 when disabled, unavailable, or on errors.
    """
    if not config.get(CONF_ENABLE_HEAT_PUMP):
        _LOGGER.debug("Heat pump integration disabled, skipping forecast")
        return 0.0

    domain, service = _get_service_config(config)
    if not hass.services.has_service(domain, service):
        _LOGGER.warning(
            "Heat pump forecast service not available: %s.%s",
            domain,
            service,
        )
        return 0.0

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
        return 0.0

    if isinstance(response, dict):
        return float(response.get("total_energy_kwh", 0.0) or 0.0)

    return 0.0
