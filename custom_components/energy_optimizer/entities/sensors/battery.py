"""Battery-related sensors for Energy Optimizer."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy

from ..base import EnergyOptimizerSensor
from ...calculations.battery import (
    calculate_battery_reserve,
    calculate_battery_space,
    calculate_total_capacity,
    calculate_usable_capacity,
)
from ...const import (
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    DEFAULT_BATTERY_CAPACITY_AH,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_BATTERY_VOLTAGE,
    DEFAULT_MAX_SOC,
    DEFAULT_MIN_SOC,
)


class BatteryReserveSensor(EnergyOptimizerSensor):
    """Sensor for battery reserve energy above minimum SOC."""

    _attr_name = "Battery Reserve"
    _attr_unique_id = "battery_reserve"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:battery-arrow-up"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        soc = self._get_state_value(self.config.get(CONF_BATTERY_SOC_SENSOR))
        if soc is None:
            return None

        return calculate_battery_reserve(
            soc,
            self.config.get(CONF_MIN_SOC, DEFAULT_MIN_SOC),
            self.config.get(CONF_BATTERY_CAPACITY_AH, DEFAULT_BATTERY_CAPACITY_AH),
            self.config.get(CONF_BATTERY_VOLTAGE, DEFAULT_BATTERY_VOLTAGE),
            efficiency=self.config.get(
                CONF_BATTERY_EFFICIENCY, DEFAULT_BATTERY_EFFICIENCY
            ),
        )


class BatterySpaceSensor(EnergyOptimizerSensor):
    """Sensor for battery space available for charging."""

    _attr_name = "Battery Space"
    _attr_unique_id = "battery_space"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:battery-arrow-down"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        soc = self._get_state_value(self.config.get(CONF_BATTERY_SOC_SENSOR))
        if soc is None:
            return None

        return calculate_battery_space(
            soc,
            self.config.get(CONF_MAX_SOC, DEFAULT_MAX_SOC),
            self.config.get(CONF_BATTERY_CAPACITY_AH, DEFAULT_BATTERY_CAPACITY_AH),
            self.config.get(CONF_BATTERY_VOLTAGE, DEFAULT_BATTERY_VOLTAGE),
        )


class BatteryCapacitySensor(EnergyOptimizerSensor):
    """Sensor for total battery capacity."""

    _attr_name = "Battery Capacity"
    _attr_unique_id = "battery_capacity"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:battery"

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        return calculate_total_capacity(
            self.config.get(CONF_BATTERY_CAPACITY_AH, DEFAULT_BATTERY_CAPACITY_AH),
            self.config.get(CONF_BATTERY_VOLTAGE, DEFAULT_BATTERY_VOLTAGE),
        )


class UsableCapacitySensor(EnergyOptimizerSensor):
    """Sensor for usable battery capacity between min and max SOC."""

    _attr_name = "Usable Capacity"
    _attr_unique_id = "usable_capacity"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:battery-heart"

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        return calculate_usable_capacity(
            self.config.get(CONF_BATTERY_CAPACITY_AH, DEFAULT_BATTERY_CAPACITY_AH),
            self.config.get(CONF_BATTERY_VOLTAGE, DEFAULT_BATTERY_VOLTAGE),
            self.config.get(CONF_MIN_SOC, DEFAULT_MIN_SOC),
            self.config.get(CONF_MAX_SOC, DEFAULT_MAX_SOC),
        )


class BatteryCapacityAhSensor(EnergyOptimizerSensor):
    """Sensor showing configured battery capacity in Ah."""

    _attr_name = "Battery Capacity (Ah)"
    _attr_unique_id = "battery_capacity_ah"
    _attr_icon = "mdi:battery-check"
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
