"""Shared logging and notification helpers for decision engine."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from homeassistant.core import HomeAssistant

from ..const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import Context


@dataclass
class DecisionOutcome:
    """Unified decision outcome data structure."""

    # Core identification
    scenario: str  # e.g., "Morning Grid Charge", "Battery Balancing"
    action_type: str  # e.g., "charge_scheduled", "balancing_enabled", "no_action"

    # Concise summary (for logs + notifications)
    summary: str  # e.g., "Set Program 2 SOC to 75%"

    # Structured details (for history sensor)
    key_metrics: dict[str, str]  # Pre-formatted strings, 3-5 items
    reason: str | None = None  # Optional explanation

    # Complete data (for last optimization sensor + events)
    full_details: dict[str, Any] = field(default_factory=dict)

    # Entity changes (for custom events)
    entities_changed: list[dict[str, Any]] = field(default_factory=list)


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


async def log_decision_unified(
    hass: HomeAssistant,
    entry: ConfigEntry,
    outcome: DecisionOutcome,
    *,
    context: Context | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Log decision outcome to all channels with unified data.
    
    This function handles all logging, notifications, sensor updates,
    and custom events from a single DecisionOutcome object, ensuring
    consistency across all output channels.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry for the integration
        outcome: DecisionOutcome object containing all decision data
        context: Optional context for linking events (recommended)
        logger: Optional logger for technical logs (e.g., _LOGGER)
    """

    # 1. Technical log
    if logger:
        logger.info("%s: %s", outcome.scenario, outcome.summary)

    # 2. User notification
    await notify_user(hass, outcome.summary)

    # 3. Last Optimization sensor (full details)
    opt_sensor, hist_sensor = get_logging_sensors(hass, entry.entry_id)
    if opt_sensor:
        opt_sensor.log_optimization(outcome.scenario, outcome.full_details)

    # 4. Optimization History sensor (structured details)
    if hist_sensor:
        history_entry = {**outcome.key_metrics}
        if outcome.reason:
            history_entry["reason"] = outcome.reason
        hist_sensor.add_entry(outcome.scenario, history_entry)

    # 5. Custom event (complete data + entity changes)
    if context:
        event_data = {
            "action": outcome.action_type,
            "description": outcome.summary,
            "scenario": outcome.scenario,
            "entry_id": entry.entry_id,
            **outcome.full_details,
        }
        if outcome.entities_changed:
            event_data["entities_changed"] = outcome.entities_changed

        hass.bus.async_fire(
            "energy_optimizer_action",
            event_data,
            context=context,
        )
