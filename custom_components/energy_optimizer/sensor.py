"""Sensor platform for Energy Optimizer integration."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.event import async_track_time_interval

from .const import CONF_BATTERY_SOC_SENSOR, DOMAIN
from .entities.sensors import (
    BatteryCapacityAhSensor,
    BatteryCapacitySensor,
    BatteryEfficiencySensor,
    BatteryReserveSensor,
    BatterySpaceSensor,
    BatteryVoltageSensor,
    LastBalancingTimestampSensor,
    LastOptimizationSensor,
    MaxSocSensor,
    MinSocSensor,
    OptimizationHistorySensor,
    PvForecastCompensationSensor,
    TestModeSensor,
    UsableCapacitySensor,
)
from .services import check_and_update_balancing_completion

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Energy Optimizer sensors from a config entry."""
    config = config_entry.data
    coordinator = hass.data[DOMAIN][config_entry.entry_id].get("coordinator")
    if coordinator is None:
        _LOGGER.error("Coordinator not available for entry %s", config_entry.entry_id)
        return

    sensors = [
        BatteryReserveSensor(coordinator, config_entry, config),
        BatterySpaceSensor(coordinator, config_entry, config),
        BatteryCapacitySensor(coordinator, config_entry, config),
        UsableCapacitySensor(coordinator, config_entry, config),
        BatteryCapacityAhSensor(coordinator, config_entry, config),
        BatteryVoltageSensor(coordinator, config_entry, config),
        BatteryEfficiencySensor(coordinator, config_entry, config),
        MinSocSensor(coordinator, config_entry, config),
        MaxSocSensor(coordinator, config_entry, config),
        TestModeSensor(coordinator, config_entry, config),
        PvForecastCompensationSensor(coordinator, config_entry, config),
    ]

    last_balancing_sensor = LastBalancingTimestampSensor(
        coordinator, config_entry, config
    )
    last_optimization_sensor = LastOptimizationSensor(coordinator, config_entry, config)
    optimization_history_sensor = OptimizationHistorySensor(
        coordinator, config_entry, config
    )

    sensors.extend(
        [last_balancing_sensor, last_optimization_sensor, optimization_history_sensor]
    )

    hass.data.setdefault(DOMAIN, {}).setdefault(config_entry.entry_id, {})[
        "last_balancing_sensor"
    ] = last_balancing_sensor
    hass.data[DOMAIN][config_entry.entry_id][
        "last_optimization_sensor"
    ] = last_optimization_sensor
    hass.data[DOMAIN][config_entry.entry_id][
        "optimization_history_sensor"
    ] = optimization_history_sensor
    hass.data[DOMAIN][config_entry.entry_id][
        "pv_forecast_compensation_sensor"
    ] = next(
        sensor
        for sensor in sensors
        if isinstance(sensor, PvForecastCompensationSensor)
    )

    if "listeners" not in hass.data[DOMAIN][config_entry.entry_id]:
        hass.data[DOMAIN][config_entry.entry_id]["listeners"] = []

    async_add_entities(sensors)

    soc_sensor = config.get(CONF_BATTERY_SOC_SENSOR)
    if soc_sensor:

        @callback
        def _async_sensor_changed(event):
            """Handle sensor state change."""
            hass.async_create_task(coordinator.async_request_refresh())

        remove_listener = async_track_state_change_event(
            hass, [soc_sensor], _async_sensor_changed
        )
        hass.data[DOMAIN][config_entry.entry_id]["listeners"].append(remove_listener)

    async def _check_balancing(_now):
        """Periodic check for balancing completion."""
        await check_and_update_balancing_completion(hass, config_entry)

    remove_listener = async_track_time_interval(
        hass, _check_balancing, timedelta(minutes=5)
    )
    hass.data[DOMAIN][config_entry.entry_id]["listeners"].append(remove_listener)

