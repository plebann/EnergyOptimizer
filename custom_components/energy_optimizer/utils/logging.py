"""Shared logging and notification helpers for decision engine."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from ..const import DOMAIN


def get_logging_sensors(
    hass: HomeAssistant, entry_id: str
) -> tuple[Any | None, Any | None]:
    """Return optimization and history sensors stored in hass.data."""

    data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not isinstance(data, dict):
        return None, None

    return (
        data.get("last_optimization_sensor"),
        data.get("optimization_history_sensor"),
    )


def log_decision(
    opt_sensor: Any | None,
    hist_sensor: Any | None,
    scenario: str,
    details: dict[str, Any],
    *,
    history_scenario: str | None = None,
    history_details: dict[str, Any] | None = None,
) -> None:
    """Log optimization details to available sensors."""

    if opt_sensor:
        opt_sensor.log_optimization(scenario, details)
    if hist_sensor:
        hist_sensor.add_entry(history_scenario or scenario, history_details or details)


async def notify_user(hass: HomeAssistant, message: str) -> None:
    """Send a notification via the default notify service."""

    await hass.services.async_call(
        "notify",
        "notify",
        {"message": message},
        blocking=False,
    )
