"""Constants for the Energy Optimizer integration."""

DOMAIN = "energy_optimizer"

# Config flow steps
CONF_PRICE_SENSOR = "price_sensor"
CONF_TOMORROW_PRICE_SENSOR = "tomorrow_price_sensor"
CONF_MIN_ARBITRAGE_PRICE = "min_arbitrage_price"
CONF_EVENING_MAX_PRICE_SENSOR = "evening_max_price_sensor"
CONF_EVENING_MAX_PRICE_HOUR_SENSOR = "evening_max_price_hour_sensor"
CONF_MORNING_MAX_PRICE_SENSOR = "morning_max_price_sensor"
CONF_MORNING_MAX_PRICE_HOUR_SENSOR = "morning_max_price_hour_sensor"
CONF_DAYTIME_MIN_PRICE_SENSOR = "daytime_min_price_sensor"

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

CONF_WORK_MODE_ENTITY = "work_mode_entity"
CONF_CHARGE_CURRENT_ENTITY = "charge_current_entity"
CONF_DISCHARGE_CURRENT_ENTITY = "discharge_current_entity"
CONF_EXPORT_POWER_ENTITY = "export_power_entity"
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
CONF_DAILY_LOSSES_SENSOR = "daily_losses_sensor"
CONF_TARIFF_START_HOUR_SENSOR = "tariff_start_hour_sensor"
CONF_TARIFF_END_HOUR_SENSOR = "tariff_end_hour_sensor"

# Time-windowed load sensors (4-hour average consumption in kWh/h)
CONF_LOAD_USAGE_00_04 = "load_usage_00_04"
CONF_LOAD_USAGE_04_08 = "load_usage_04_08"
CONF_LOAD_USAGE_08_12 = "load_usage_08_12"
CONF_LOAD_USAGE_12_16 = "load_usage_12_16"
CONF_LOAD_USAGE_16_20 = "load_usage_16_20"
CONF_LOAD_USAGE_20_24 = "load_usage_20_24"

# Today's consumption tracking for dynamic ratio
CONF_TODAY_LOAD_SENSOR = "today_load_sensor"

CONF_PV_FORECAST_TODAY = "pv_forecast_today"
CONF_PV_FORECAST_TOMORROW = "pv_forecast_tomorrow"
CONF_PV_FORECAST_REMAINING = "pv_forecast_remaining"
CONF_PV_PRODUCTION_SENSOR = "pv_production_sensor"
CONF_PV_PEAK_FORECAST = "pv_peak_forecast"
CONF_WEATHER_FORECAST = "weather_forecast"
CONF_PV_FORECAST_SENSOR = "pv_forecast_sensor"
CONF_PV_EFFICIENCY = "pv_efficiency"

CONF_ENABLE_HEAT_PUMP = "enable_heat_pump"
CONF_HEAT_PUMP_FORECAST_DOMAIN = "heat_pump_forecast_domain"
CONF_HEAT_PUMP_FORECAST_SERVICE = "heat_pump_forecast_service"

# Battery balancing configuration
CONF_BALANCING_INTERVAL_DAYS = "balancing_interval_days"
CONF_BALANCING_PV_THRESHOLD = "balancing_pv_threshold_kwh"
CONF_MAX_CHARGE_CURRENT_ENTITY = "max_charge_current_entity"
CONF_TEST_MODE = "test_mode"
CONF_TEST_SELL_MODE = "test_sell_mode"

# Default values
DEFAULT_BATTERY_CAPACITY_AH = 37
DEFAULT_BATTERY_VOLTAGE = 640
DEFAULT_BATTERY_EFFICIENCY = 95
DEFAULT_MIN_SOC = 15
DEFAULT_MAX_SOC = 100
DEFAULT_BALANCING_INTERVAL_DAYS = 14
DEFAULT_BALANCING_PV_THRESHOLD = 20.5
DEFAULT_MAX_CHARGE_CURRENT = 23
DEFAULT_PV_EFFICIENCY = 0.9
DEFAULT_MIN_ARBITRAGE_PRICE = 0.0
DEFAULT_HEAT_PUMP_FORECAST_DOMAIN = "heat_pump_predictor"
DEFAULT_HEAT_PUMP_FORECAST_SERVICE = "calculate_forecast_energy"

# Services
SERVICE_OVERNIGHT_SCHEDULE = "overnight_schedule"
SERVICE_MORNING_GRID_CHARGE = "morning_grid_charge"
SERVICE_AFTERNOON_GRID_CHARGE = "afternoon_grid_charge"
SERVICE_EVENING_PEAK_SELL = "evening_peak_sell"

DEFAULT_EXPORT_POWER_RESET = 12000
DEFAULT_DISCHARGE_CURRENT_RESET = 12

# Update intervals (seconds)
UPDATE_INTERVAL_FAST = 60  # For battery-related sensors
UPDATE_INTERVAL_SLOW = 3600  # For daily forecasts
