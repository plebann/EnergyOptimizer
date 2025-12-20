"""Sensor platform for Energy Optimizer integration."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .calculations.battery import (
    calculate_battery_reserve,
    calculate_battery_space,
    calculate_total_capacity,
    calculate_usable_capacity,
)
from .calculations.energy import calculate_required_energy, calculate_surplus_energy
from .calculations.heat_pump import estimate_daily_consumption
from .const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_COP_CURVE,
    CONF_DAILY_LOAD_SENSOR,
    CONF_ENABLE_HEAT_PUMP,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_PV_FORECAST_TODAY,
    DEFAULT_COP_CURVE,
    DOMAIN,
    UPDATE_INTERVAL_FAST,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Energy Optimizer sensors from a config entry."""
    config = config_entry.data

    # Create coordinator for sensor updates
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="energy_optimizer",
        update_interval=timedelta(seconds=UPDATE_INTERVAL_FAST),
    )

    # Create sensors
    sensors: list[SensorEntity] = [
        BatteryReserveSensor(coordinator, config_entry, config),
        BatterySpaceSensor(coordinator, config_entry, config),
        BatteryCapacitySensor(coordinator, config_entry, config),
        UsableCapacitySensor(coordinator, config_entry, config),
    ]

    # Add energy balance sensors if daily load sensor configured
    if config.get(CONF_DAILY_LOAD_SENSOR):
        sensors.extend(
            [
                RequiredEnergyMorningSensor(coordinator, config_entry, config),
                RequiredEnergyAfternoonSensor(coordinator, config_entry, config),
                RequiredEnergyEveningSensor(coordinator, config_entry, config),
                SurplusEnergySensor(coordinator, config_entry, config),
            ]
        )

    # Add heat pump sensor if enabled
    if config.get(CONF_ENABLE_HEAT_PUMP) and config.get(CONF_OUTSIDE_TEMP_SENSOR):
        sensors.append(HeatPumpEstimationSensor(coordinator, config_entry, config))

    async_add_entities(sensors)

    # Track state changes for battery sensors
    soc_sensor = config.get(CONF_BATTERY_SOC_SENSOR)
    if soc_sensor:

        @callback
        def _async_sensor_changed(event):
            """Handle sensor state change."""
            coordinator.async_set_updated_data(None)

        async_track_state_change_event(hass, [soc_sensor], _async_sensor_changed)


class EnergyOptimizerSensor(SensorEntity):
    """Base class for Energy Optimizer sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        config: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self.config_entry = config_entry
        self.config = config
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": "Energy Optimizer",
            "manufacturer": "Energy Optimizer",
            "model": "Battery Optimizer",
        }

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    def _get_sensor_state(self, entity_id: str) -> float | None:
        """Get sensor state as float."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None


class BatteryReserveSensor(EnergyOptimizerSensor):
    """Sensor for battery reserve energy above minimum SOC."""

    _attr_name = "Battery Reserve"
    _attr_unique_id = "battery_reserve"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:battery-arrow-up"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        soc = self._get_sensor_state(self.config.get(CONF_BATTERY_SOC_SENSOR))
        if soc is None:
            return None

        return calculate_battery_reserve(
            soc,
            self.config.get(CONF_MIN_SOC, 10),
            self.config.get(CONF_BATTERY_CAPACITY_AH, 200),
            self.config.get(CONF_BATTERY_VOLTAGE, 48),
        )


class BatterySpaceSensor(EnergyOptimizerSensor):
    """Sensor for battery space available for charging."""

    _attr_name = "Battery Space"
    _attr_unique_id = "battery_space"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:battery-arrow-down"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        soc = self._get_sensor_state(self.config.get(CONF_BATTERY_SOC_SENSOR))
        if soc is None:
            return None

        return calculate_battery_space(
            soc,
            self.config.get(CONF_MAX_SOC, 100),
            self.config.get(CONF_BATTERY_CAPACITY_AH, 200),
            self.config.get(CONF_BATTERY_VOLTAGE, 48),
        )


class BatteryCapacitySensor(EnergyOptimizerSensor):
    """Sensor for total battery capacity."""

    _attr_name = "Battery Capacity"
    _attr_unique_id = "battery_capacity"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:battery"

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        return calculate_total_capacity(
            self.config.get(CONF_BATTERY_CAPACITY_AH, 200),
            self.config.get(CONF_BATTERY_VOLTAGE, 48),
        )


class UsableCapacitySensor(EnergyOptimizerSensor):
    """Sensor for usable battery capacity between min and max SOC."""

    _attr_name = "Usable Capacity"
    _attr_unique_id = "usable_capacity"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:battery-check"

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        return calculate_usable_capacity(
            self.config.get(CONF_BATTERY_CAPACITY_AH, 200),
            self.config.get(CONF_BATTERY_VOLTAGE, 48),
            self.config.get(CONF_MIN_SOC, 10),
            self.config.get(CONF_MAX_SOC, 100),
        )


class RequiredEnergyMorningSensor(EnergyOptimizerSensor):
    """Sensor for required energy until noon."""

    _attr_name = "Required Energy Morning"
    _attr_unique_id = "required_energy_morning"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:weather-sunset-up"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        # Simplified calculation - should use history API in production
        daily_load = self._get_sensor_state(self.config.get(CONF_DAILY_LOAD_SENSOR))
        if daily_load is None:
            return None

        hourly_usage = daily_load / 24
        return calculate_required_energy(
            hourly_usage,
            12,  # Morning until noon
            self.config.get(CONF_BATTERY_EFFICIENCY, 95),
        )


class RequiredEnergyAfternoonSensor(EnergyOptimizerSensor):
    """Sensor for required energy in afternoon."""

    _attr_name = "Required Energy Afternoon"
    _attr_unique_id = "required_energy_afternoon"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:weather-sunny"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        daily_load = self._get_sensor_state(self.config.get(CONF_DAILY_LOAD_SENSOR))
        if daily_load is None:
            return None

        hourly_usage = daily_load / 24
        return calculate_required_energy(
            hourly_usage,
            6,  # Afternoon 12:00-18:00
            self.config.get(CONF_BATTERY_EFFICIENCY, 95),
        )


class RequiredEnergyEveningSensor(EnergyOptimizerSensor):
    """Sensor for required energy in evening."""

    _attr_name = "Required Energy Evening"
    _attr_unique_id = "required_energy_evening"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:weather-night"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        daily_load = self._get_sensor_state(self.config.get(CONF_DAILY_LOAD_SENSOR))
        if daily_load is None:
            return None

        hourly_usage = daily_load / 24
        return calculate_required_energy(
            hourly_usage,
            4,  # Evening 18:00-22:00
            self.config.get(CONF_BATTERY_EFFICIENCY, 95),
        )


class SurplusEnergySensor(EnergyOptimizerSensor):
    """Sensor for surplus energy available above requirements."""

    _attr_name = "Surplus Energy"
    _attr_unique_id = "surplus_energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:battery-plus"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        soc = self._get_sensor_state(self.config.get(CONF_BATTERY_SOC_SENSOR))
        daily_load = self._get_sensor_state(self.config.get(CONF_DAILY_LOAD_SENSOR))

        if soc is None or daily_load is None:
            return None

        # Calculate battery reserve
        battery_reserve = calculate_battery_reserve(
            soc,
            self.config.get(CONF_MIN_SOC, 10),
            self.config.get(CONF_BATTERY_CAPACITY_AH, 200),
            self.config.get(CONF_BATTERY_VOLTAGE, 48),
        )

        # Calculate required energy (simplified)
        hourly_usage = daily_load / 24
        required_energy = calculate_required_energy(
            hourly_usage, 6, self.config.get(CONF_BATTERY_EFFICIENCY, 95)
        )

        # Get PV forecast if available
        pv_forecast = 0.0
        if self.config.get(CONF_PV_FORECAST_TODAY):
            pv_forecast = (
                self._get_sensor_state(self.config.get(CONF_PV_FORECAST_TODAY)) or 0.0
            )

        return calculate_surplus_energy(battery_reserve, required_energy, pv_forecast)


class HeatPumpEstimationSensor(EnergyOptimizerSensor):
    """Sensor for daily heat pump consumption estimation."""

    _attr_name = "Heat Pump Estimation"
    _attr_unique_id = "heat_pump_estimation"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:heat-pump"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        temp = self._get_sensor_state(self.config.get(CONF_OUTSIDE_TEMP_SENSOR))
        if temp is None:
            return None

        # Simplified: use current temp as average, estimate min/max
        min_temp = temp - 5
        max_temp = temp + 5

        cop_curve = self.config.get(CONF_COP_CURVE, DEFAULT_COP_CURVE)

        return estimate_daily_consumption(
            min_temp=min_temp,
            max_temp=max_temp,
            avg_temp=temp,
            cop_curve=cop_curve,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        temp = self._get_sensor_state(self.config.get(CONF_OUTSIDE_TEMP_SENSOR))
        if temp is None:
            return {}

        return {
            "outside_temperature": temp,
            "estimated_min_temp": temp - 5,
            "estimated_max_temp": temp + 5,
        }
