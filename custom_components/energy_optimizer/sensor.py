"""Sensor platform for Energy Optimizer integration."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

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
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_COP_CURVE,
    CONF_DAILY_LOAD_SENSOR,
    CONF_DAILY_LOSSES_SENSOR,
    CONF_ENABLE_HEAT_PUMP,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_PV_FORECAST_TODAY,
    DEFAULT_BATTERY_CAPACITY_AH,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_BATTERY_VOLTAGE,
    DEFAULT_COP_CURVE,
    DEFAULT_MAX_SOC,
    DEFAULT_MIN_SOC,
    DOMAIN,
    SENSOR_LAST_BALANCING_TIMESTAMP,
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
        # Configuration value sensors
        BatteryCapacityAhSensor(coordinator, config_entry, config),
        BatteryVoltageSensor(coordinator, config_entry, config),
        BatteryEfficiencySensor(coordinator, config_entry, config),
        MinSocSensor(coordinator, config_entry, config),
        MaxSocSensor(coordinator, config_entry, config),
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

    # Add last balancing timestamp sensor
    last_balancing_sensor = LastBalancingTimestampSensor(
        coordinator, config_entry, config
    )
    sensors.append(last_balancing_sensor)

    # Add optimization tracking sensors
    last_optimization_sensor = LastOptimizationSensor(
        coordinator, config_entry, config
    )
    sensors.append(last_optimization_sensor)

    optimization_history_sensor = OptimizationHistorySensor(
        coordinator, config_entry, config
    )
    sensors.append(optimization_history_sensor)

    # Store sensor references for service access
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    if config_entry.entry_id not in hass.data[DOMAIN]:
        hass.data[DOMAIN][config_entry.entry_id] = {}
    hass.data[DOMAIN][config_entry.entry_id][
        "last_balancing_sensor"
    ] = last_balancing_sensor
    hass.data[DOMAIN][config_entry.entry_id][
        "last_optimization_sensor"
    ] = last_optimization_sensor
    hass.data[DOMAIN][config_entry.entry_id][
        "optimization_history_sensor"
    ] = optimization_history_sensor

    async_add_entities(sensors)

    # Track state changes for battery sensors
    soc_sensor = config.get(CONF_BATTERY_SOC_SENSOR)
    if soc_sensor:

        @callback
        def _async_sensor_changed(event):
            """Handle sensor state change."""
            coordinator.async_set_updated_data(None)

        async_track_state_change_event(hass, [soc_sensor], _async_sensor_changed)

    # Set up periodic balancing completion check (every 5 minutes)
    from homeassistant.helpers.event import async_track_time_interval
    from .services import check_and_update_balancing_completion
    
    async def _check_balancing(_now):
        """Periodic check for balancing completion."""
        await check_and_update_balancing_completion(hass, config_entry)
    
    async_track_time_interval(hass, _check_balancing, timedelta(minutes=5))


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
        from datetime import datetime
        from .calculations.energy import calculate_required_energy_windowed
        
        # Try time-windowed calculation first
        if self._has_time_windowed_config():
            now = datetime.now()
            try:
                return calculate_required_energy_windowed(
                    start_hour=0,
                    end_hour=12,
                    config=self.config,
                    hass_states_get=self.hass.states.get,
                    efficiency=self.config.get(CONF_BATTERY_EFFICIENCY, 95),
                    current_hour=now.hour,
                    current_minute=now.minute,
                )
            except Exception as ex:
                _LOGGER.warning(
                    "Time-windowed calculation failed for %s, falling back: %s",
                    self.name, ex
                )
        
        # Fallback to legacy calculation
        daily_load = self._get_sensor_state(self.config.get(CONF_DAILY_LOAD_SENSOR))
        if daily_load is None:
            return None

        hourly_usage = daily_load / 24
        return calculate_required_energy(
            hourly_usage,
            0,
            12,  # Morning until noon
            self.config.get(CONF_BATTERY_EFFICIENCY, 95),
        )
    
    def _has_time_windowed_config(self) -> bool:
        """Check if time-windowed sensors are configured."""
        from .const import (
            CONF_LOAD_USAGE_00_04,
            CONF_LOAD_USAGE_04_08,
            CONF_LOAD_USAGE_08_12,
            CONF_LOAD_USAGE_12_16,
            CONF_LOAD_USAGE_16_20,
            CONF_LOAD_USAGE_20_24,
        )
        
        return any(
            self.config.get(key)
            for key in [
                CONF_LOAD_USAGE_00_04,
                CONF_LOAD_USAGE_04_08,
                CONF_LOAD_USAGE_08_12,
                CONF_LOAD_USAGE_12_16,
                CONF_LOAD_USAGE_16_20,
                CONF_LOAD_USAGE_20_24,
            ]
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
        from datetime import datetime
        from .calculations.energy import calculate_required_energy_windowed
        
        # Try time-windowed calculation first
        if self._has_time_windowed_config():
            now = datetime.now()
            try:
                return calculate_required_energy_windowed(
                    start_hour=12,
                    end_hour=18,
                    config=self.config,
                    hass_states_get=self.hass.states.get,
                    efficiency=self.config.get(CONF_BATTERY_EFFICIENCY, 95),
                    current_hour=now.hour,
                    current_minute=now.minute,
                )
            except Exception as ex:
                _LOGGER.warning(
                    "Time-windowed calculation failed for %s, falling back: %s",
                    self.name, ex
                )
        
        # Fallback to legacy calculation
        daily_load = self._get_sensor_state(self.config.get(CONF_DAILY_LOAD_SENSOR))
        if daily_load is None:
            return None

        hourly_usage = daily_load / 24
        return calculate_required_energy(
            hourly_usage,
            0,
            6,  # Afternoon 12:00-18:00
            self.config.get(CONF_BATTERY_EFFICIENCY, 95),
        )
    
    def _has_time_windowed_config(self) -> bool:
        """Check if time-windowed sensors are configured."""
        from .const import (
            CONF_LOAD_USAGE_00_04,
            CONF_LOAD_USAGE_04_08,
            CONF_LOAD_USAGE_08_12,
            CONF_LOAD_USAGE_12_16,
            CONF_LOAD_USAGE_16_20,
            CONF_LOAD_USAGE_20_24,
        )
        
        return any(
            self.config.get(key)
            for key in [
                CONF_LOAD_USAGE_00_04,
                CONF_LOAD_USAGE_04_08,
                CONF_LOAD_USAGE_08_12,
                CONF_LOAD_USAGE_12_16,
                CONF_LOAD_USAGE_16_20,
                CONF_LOAD_USAGE_20_24,
            ]
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
        from datetime import datetime
        from .calculations.energy import calculate_required_energy_windowed
        
        # Try time-windowed calculation first
        if self._has_time_windowed_config():
            now = datetime.now()
            try:
                return calculate_required_energy_windowed(
                    start_hour=18,
                    end_hour=22,
                    config=self.config,
                    hass_states_get=self.hass.states.get,
                    efficiency=self.config.get(CONF_BATTERY_EFFICIENCY, 95),
                    current_hour=now.hour,
                    current_minute=now.minute,
                )
            except Exception as ex:
                _LOGGER.warning(
                    "Time-windowed calculation failed for %s, falling back: %s",
                    self.name, ex
                )
        
        # Fallback to legacy calculation
        daily_load = self._get_sensor_state(self.config.get(CONF_DAILY_LOAD_SENSOR))
        if daily_load is None:
            return None
        daily_losses = self._get_sensor_state(self.config.get(CONF_DAILY_LOSSES_SENSOR))
        if daily_losses is None:
            return None

        hourly_usage = daily_load / 24
        hourly_losses = daily_losses / 24
        return calculate_required_energy(
            hourly_usage,
            0,
            4,  # Evening 18:00-22:00
            self.config.get(CONF_BATTERY_EFFICIENCY, 95),
        )
    
    def _has_time_windowed_config(self) -> bool:
        """Check if time-windowed sensors are configured."""
        from .const import (
            CONF_LOAD_USAGE_00_04,
            CONF_LOAD_USAGE_04_08,
            CONF_LOAD_USAGE_08_12,
            CONF_LOAD_USAGE_12_16,
            CONF_LOAD_USAGE_16_20,
            CONF_LOAD_USAGE_20_24,
        )
        
        return any(
            self.config.get(key)
            for key in [
                CONF_LOAD_USAGE_00_04,
                CONF_LOAD_USAGE_04_08,
                CONF_LOAD_USAGE_08_12,
                CONF_LOAD_USAGE_12_16,
                CONF_LOAD_USAGE_16_20,
                CONF_LOAD_USAGE_20_24,
            ]
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
            hourly_usage, 0, 6, self.config.get(CONF_BATTERY_EFFICIENCY, 95)
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


class LastBalancingTimestampSensor(EnergyOptimizerSensor, RestoreSensor):
    """Sensor tracking last battery balancing timestamp."""

    _attr_name = "Last Battery Balancing"
    _attr_unique_id = "last_balancing_timestamp"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:battery-charging-100"
    _attr_native_value: datetime | None = None
    _attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Restore last state on startup."""
        await super().async_added_to_hass()

        # Restore previous timestamp
        if (restored_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = restored_data.native_value
            _LOGGER.debug(
                "Restored last balancing timestamp: %s", self._attr_native_value
            )

    @property
    def native_value(self) -> datetime | None:
        """Return the last balancing timestamp."""
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        return self._attr_extra_state_attributes

    def update_balancing_timestamp(self, timestamp: datetime | None = None) -> None:
        """Update the balancing timestamp (called from service)."""
        if timestamp is None:
            timestamp = dt_util.utcnow()
        self._attr_native_value = timestamp
        self.async_write_ha_state()
        _LOGGER.debug("Updated balancing timestamp to %s", timestamp)


class OptimizationExtraStoredData(ExtraStoredData):
    """Custom ExtraStoredData for LastOptimizationSensor."""

    def __init__(
        self,
        native_value: datetime | None,
        scenario: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the stored data."""
        self.native_value = native_value
        self.scenario = scenario
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        """Return dict representation."""
        return {
            "native_value": self.native_value.isoformat() if self.native_value else None,
            "scenario": self.scenario,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OptimizationExtraStoredData:
        """Restore from dict."""
        native_value = None
        if data.get("native_value"):
            native_value = datetime.fromisoformat(data["native_value"])
        return cls(
            native_value=native_value,
            scenario=data.get("scenario"),
            details=data.get("details", {}),
        )


class HistoryExtraStoredData(ExtraStoredData):
    """Custom ExtraStoredData for OptimizationHistorySensor."""

    def __init__(
        self,
        native_value: str,
        history: list[dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the stored data."""
        self.native_value = native_value
        self.history = history or []

    def as_dict(self) -> dict[str, Any]:
        """Return dict representation."""
        return {
            "native_value": self.native_value,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryExtraStoredData:
        """Restore from dict."""
        history = data.get("history", [])
        # Validate history entries
        if not isinstance(history, list):
            history = []
        # Keep only last 50 entries during restoration
        history = history[-50:] if len(history) > 50 else history
        return cls(
            native_value=data.get("native_value", "No optimizations yet"),
            history=history,
        )


class LastOptimizationSensor(EnergyOptimizerSensor, RestoreSensor):
    """Sensor tracking last optimization run and decision."""

    _attr_name = "Last Optimization"
    _attr_unique_id = "last_optimization"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"
    _attr_native_value: datetime | None = None
    _attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Restore last state on startup."""
        await super().async_added_to_hass()

        # Restore from custom ExtraStoredData
        if (extra_data := await self.async_get_last_extra_data()) is not None:
            if isinstance(extra_data, OptimizationExtraStoredData):
                self._attr_native_value = extra_data.native_value
                if extra_data.scenario:
                    self._attr_extra_state_attributes = {
                        "scenario": extra_data.scenario,
                        **extra_data.details,
                    }
                _LOGGER.info(
                    "Restored LastOptimizationSensor: %s (scenario: %s)",
                    self._attr_native_value,
                    extra_data.scenario,
                )
            else:
                _LOGGER.warning("Unexpected extra data type for LastOptimizationSensor")

    @property
    def native_value(self) -> datetime | None:
        """Return the last optimization timestamp."""
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        return self._attr_extra_state_attributes

    @property
    def extra_restore_state_data(self) -> OptimizationExtraStoredData | None:
        """Return extra data to persist."""
        if self._attr_native_value is None:
            return None
        scenario = self._attr_extra_state_attributes.get("scenario")
        # Extract details (all attributes except scenario and timestamp_local)
        details = {
            k: v
            for k, v in self._attr_extra_state_attributes.items()
            if k not in ("scenario", "timestamp_local")
        }
        return OptimizationExtraStoredData(
            native_value=self._attr_native_value,
            scenario=scenario,
            details=details,
        )

    def log_optimization(self, scenario: str, details: dict[str, Any]) -> None:
        """Log an optimization run (called from service)."""
        self._attr_native_value = dt_util.utcnow()
        self._attr_extra_state_attributes = {
            "scenario": scenario,
            "timestamp_local": dt_util.now().isoformat(),
            **details,
        }
        self.async_write_ha_state()
        _LOGGER.debug("Logged optimization: %s - %s", scenario, details)


class BatteryCapacityAhSensor(EnergyOptimizerSensor):
    """Sensor showing configured battery capacity in Ah."""

    _attr_name = "Battery Capacity (Ah)"
    _attr_unique_id = "battery_capacity_ah"
    _attr_icon = "mdi:battery-settings"
    _attr_native_unit_of_measurement = "Ah"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float:
        """Return the configured battery capacity in Ah."""
        return self.config.get(CONF_BATTERY_CAPACITY_AH, DEFAULT_BATTERY_CAPACITY_AH)


class BatteryVoltageSensor(EnergyOptimizerSensor):
    """Sensor showing configured battery voltage."""

    _attr_name = "Battery Voltage"
    _attr_unique_id = "battery_voltage_config"
    _attr_icon = "mdi:lightning-bolt"
    _attr_native_unit_of_measurement = "V"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float:
        """Return the configured battery voltage."""
        return self.config.get(CONF_BATTERY_VOLTAGE, DEFAULT_BATTERY_VOLTAGE)


class BatteryEfficiencySensor(EnergyOptimizerSensor):
    """Sensor showing configured battery efficiency."""

    _attr_name = "Battery Efficiency"
    _attr_unique_id = "battery_efficiency_config"
    _attr_icon = "mdi:percent"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float:
        """Return the configured battery efficiency."""
        return self.config.get(CONF_BATTERY_EFFICIENCY, DEFAULT_BATTERY_EFFICIENCY)


class MinSocSensor(EnergyOptimizerSensor):
    """Sensor showing configured minimum SOC."""

    _attr_name = "Minimum SOC"
    _attr_unique_id = "min_soc_config"
    _attr_icon = "mdi:battery-low"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int:
        """Return the configured minimum SOC."""
        return self.config.get(CONF_MIN_SOC, DEFAULT_MIN_SOC)


class MaxSocSensor(EnergyOptimizerSensor):
    """Sensor showing configured maximum SOC."""

    _attr_name = "Maximum SOC"
    _attr_unique_id = "max_soc_config"
    _attr_icon = "mdi:battery-high"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int:
        """Return the configured maximum SOC."""
        return self.config.get(CONF_MAX_SOC, DEFAULT_MAX_SOC)


class OptimizationHistorySensor(EnergyOptimizerSensor, RestoreSensor):
    """Sensor showing recent optimization history as text."""

    _attr_name = "Optimization History"
    _attr_unique_id = "optimization_history"
    _attr_icon = "mdi:history"
    _attr_native_value: str = "No optimizations yet"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        config: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry, config)
        self._history: list[dict[str, Any]] = []

    async def async_added_to_hass(self) -> None:
        """Restore history on startup."""
        await super().async_added_to_hass()

        # Restore from custom ExtraStoredData
        if (extra_data := await self.async_get_last_extra_data()) is not None:
            if isinstance(extra_data, HistoryExtraStoredData):
                self._attr_native_value = extra_data.native_value
                self._history = extra_data.history
                _LOGGER.info(
                    "Restored OptimizationHistorySensor: %d entries",
                    len(self._history),
                )
            else:
                _LOGGER.warning("Unexpected extra data type for OptimizationHistorySensor")

    @property
    def native_value(self) -> str:
        """Return the most recent optimization as text."""
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full history in attributes."""
        return {"history": self._history[-10:]}  # Keep last 10 entries

    @property
    def extra_restore_state_data(self) -> HistoryExtraStoredData | None:
        """Return extra data to persist."""
        if not self._history:
            return None
        return HistoryExtraStoredData(
            native_value=self._attr_native_value,
            history=self._history,
        )

    def add_entry(self, scenario: str, details: dict[str, Any]) -> None:
        """Add a new history entry."""
        timestamp = dt_util.now()
        entry = {
            "time": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "scenario": scenario,
            **details,
        }
        self._history.append(entry)
        
        # Keep only last 50 entries in memory
        if len(self._history) > 50:
            self._history = self._history[-50:]
        
        # Update display value to show most recent
        self._attr_native_value = f"{timestamp.strftime('%H:%M:%S')} - {scenario}"
        self.async_write_ha_state()
        _LOGGER.debug("Added optimization history entry: %s", entry)
