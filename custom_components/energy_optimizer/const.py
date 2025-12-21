"""Constants for the Energy Optimizer integration."""

DOMAIN = "energy_optimizer"

# Config flow steps
CONF_PRICE_SENSOR = "price_sensor"
CONF_AVERAGE_PRICE_SENSOR = "average_price_sensor"
CONF_CHEAPEST_WINDOW_SENSOR = "cheapest_window_sensor"
CONF_EXPENSIVE_WINDOW_SENSOR = "expensive_window_sensor"
CONF_TOMORROW_PRICE_SENSOR = "tomorrow_price_sensor"

CONF_BATTERY_SOC_SENSOR = "battery_soc_sensor"
CONF_BATTERY_POWER_SENSOR = "battery_power_sensor"
CONF_BATTERY_VOLTAGE_SENSOR = "battery_voltage_sensor"
CONF_BATTERY_CURRENT_SENSOR = "battery_current_sensor"

CONF_BATTERY_CAPACITY_AH = "battery_capacity_ah"
CONF_BATTERY_VOLTAGE = "battery_voltage"
CONF_BATTERY_EFFICIENCY = "battery_efficiency"
CONF_MIN_SOC = "min_soc"
CONF_MAX_SOC = "max_soc"
CONF_BATTERY_CAPACITY_ENTITY = "battery_capacity_entity"

CONF_TARGET_SOC_ENTITY = "target_soc_entity"
CONF_WORK_MODE_ENTITY = "work_mode_entity"
CONF_CHARGE_CURRENT_ENTITY = "charge_current_entity"
CONF_DISCHARGE_CURRENT_ENTITY = "discharge_current_entity"
CONF_GRID_CHARGE_SWITCH = "grid_charge_switch"

# Time-based program SOC entities (for Solarman inverters with multiple time slots)
CONF_PROG1_SOC_ENTITY = "prog1_soc_entity"
CONF_PROG2_SOC_ENTITY = "prog2_soc_entity"
CONF_PROG3_SOC_ENTITY = "prog3_soc_entity"
CONF_PROG4_SOC_ENTITY = "prog4_soc_entity"
CONF_PROG5_SOC_ENTITY = "prog5_soc_entity"
CONF_PROG6_SOC_ENTITY = "prog6_soc_entity"

# Time start entities for each program (input_datetime or sensor entities with time values)
# Programs run from start time to next program's start time
CONF_PROG1_TIME_START_ENTITY = "prog1_time_start_entity"
CONF_PROG2_TIME_START_ENTITY = "prog2_time_start_entity"
CONF_PROG3_TIME_START_ENTITY = "prog3_time_start_entity"
CONF_PROG4_TIME_START_ENTITY = "prog4_time_start_entity"
CONF_PROG5_TIME_START_ENTITY = "prog5_time_start_entity"
CONF_PROG6_TIME_START_ENTITY = "prog6_time_start_entity"

CONF_DAILY_LOAD_SENSOR = "daily_load_sensor"
CONF_PV_FORECAST_TODAY = "pv_forecast_today"
CONF_PV_FORECAST_TOMORROW = "pv_forecast_tomorrow"
CONF_PV_FORECAST_REMAINING = "pv_forecast_remaining"
CONF_PV_PEAK_FORECAST = "pv_peak_forecast"
CONF_WEATHER_FORECAST = "weather_forecast"

CONF_ENABLE_HEAT_PUMP = "enable_heat_pump"
CONF_OUTSIDE_TEMP_SENSOR = "outside_temp_sensor"
CONF_HEAT_PUMP_POWER_SENSOR = "heat_pump_power_sensor"
CONF_COP_CURVE = "cop_curve"

# Battery balancing configuration
CONF_BALANCING_INTERVAL_DAYS = "balancing_interval_days"
CONF_BALANCING_PV_THRESHOLD = "balancing_pv_threshold_kwh"
CONF_PROGRAM_NIGHT_SOC_ENTITY = "program_night_soc_entity"
CONF_PROGRAM_MORNING_SOC_ENTITY = "program_morning_soc_entity"
CONF_MAX_CHARGE_CURRENT_ENTITY = "max_charge_current_entity"

# Default values
DEFAULT_BATTERY_CAPACITY_AH = 200
DEFAULT_BATTERY_VOLTAGE = 48
DEFAULT_BATTERY_EFFICIENCY = 95
DEFAULT_MIN_SOC = 10
DEFAULT_MAX_SOC = 100
DEFAULT_BALANCING_INTERVAL_DAYS = 14
DEFAULT_BALANCING_PV_THRESHOLD = 20.5

# Default COP curve (temperature °C, COP)
DEFAULT_COP_CURVE = [
    (-20, 2.0),
    (-10, 2.3),
    (-5, 2.6),
    (0, 3.0),
    (5, 3.5),
    (10, 4.0),
    (15, 4.5),
    (20, 5.0),
]

# Services
SERVICE_CALCULATE_CHARGE_SOC = "calculate_charge_soc"
SERVICE_CALCULATE_SELL_ENERGY = "calculate_sell_energy"
SERVICE_ESTIMATE_HEAT_PUMP = "estimate_heat_pump_usage"
SERVICE_OPTIMIZE_SCHEDULE = "optimize_battery_schedule"

# Sensor types
SENSOR_BATTERY_RESERVE = "battery_reserve"
SENSOR_BATTERY_SPACE = "battery_space"
SENSOR_BATTERY_CAPACITY = "battery_capacity"
SENSOR_USABLE_CAPACITY = "usable_capacity"
SENSOR_REQUIRED_ENERGY_MORNING = "required_energy_morning"
SENSOR_REQUIRED_ENERGY_AFTERNOON = "required_energy_afternoon"
SENSOR_REQUIRED_ENERGY_EVENING = "required_energy_evening"
SENSOR_SURPLUS_ENERGY = "surplus_energy"
SENSOR_ENERGY_DEFICIT = "energy_deficit"
SENSOR_HEAT_PUMP_ESTIMATION = "heat_pump_estimation"
SENSOR_LAST_BALANCING_TIMESTAMP = "last_balancing_timestamp"
SENSOR_LAST_OPTIMIZATION = "last_optimization"
SENSOR_OPTIMIZATION_HISTORY = "optimization_history"

# Update intervals (seconds)
UPDATE_INTERVAL_FAST = 60  # For battery-related sensors
UPDATE_INTERVAL_MEDIUM = 300  # For energy balance sensors
UPDATE_INTERVAL_SLOW = 3600  # For daily forecasts
