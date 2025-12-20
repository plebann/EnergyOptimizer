<!-- markdownlint-disable-file -->
# Task Details: Energy Optimizer HACS Integration Implementation

## Research Reference

**Source Research**: #file:../research/20241219-energy-optimizer-hacs-migration-research.md

## Phase 1: Project Structure & Manifest

### Task 1.1: Create integration directory structure

Create the standard Home Assistant custom integration directory structure following HACS requirements.

- **Files**:
  - `custom_components/energy_optimizer/__init__.py` - Integration entry point
  - `custom_components/energy_optimizer/manifest.json` - Integration metadata
  - `custom_components/energy_optimizer/const.py` - Constants and configuration keys
  - `custom_components/energy_optimizer/config_flow.py` - UI configuration flow
  - `custom_components/energy_optimizer/sensor.py` - Sensor platform
  - `custom_components/energy_optimizer/services.yaml` - Service definitions
  - `custom_components/energy_optimizer/strings.json` - UI translations
  - `custom_components/energy_optimizer/calculations/__init__.py` - Calculation library
- **Success**:
  - Directory structure matches HACS requirements
  - All __init__.py files are present for Python packages
  - Structure follows Home Assistant integration patterns
- **Research References**:
  - #file:../research/20241219-energy-optimizer-hacs-migration-research.md (Lines 117-146) - Repository structure requirements
  - #file:../research/20241219-architecture-summary.md (Lines 568-583) - Integration directory structure
- **Dependencies**:
  - None (first task)

### Task 1.2: Create manifest.json with metadata and dependencies

Create integration manifest following Home Assistant requirements with proper metadata, dependencies, and version info.

- **Files**:
  - `custom_components/energy_optimizer/manifest.json` - Integration manifest
- **Content Structure**:
  ```json
  {
    "domain": "energy_optimizer",
    "name": "Energy Optimizer",
    "codeowners": ["@plebann"],
    "config_flow": true,
    "documentation": "https://github.com/plebann/EnergyOptimizer",
    "issue_tracker": "https://github.com/plebann/EnergyOptimizer/issues",
    "iot_class": "calculated",
    "requirements": [],
    "version": "1.0.0",
    "after_dependencies": ["rce_pse", "solarman", "solcast_solar"]
  }
  ```
- **Success**:
  - Manifest passes Home Assistant validation
  - `after_dependencies` ensures proper load order
  - `iot_class: calculated` reflects entity-based design
  - `config_flow: true` enables UI configuration
- **Research References**:
  - #file:../research/20241219-energy-optimizer-hacs-migration-research.md (Lines 148-154) - Manifest requirements
  - #file:../research/20241219-architecture-summary.md (Lines 30-35) - Integration dependencies
- **Dependencies**:
  - Task 1.1 completion (directory structure)

### Task 1.3: Create const.py with domain constants and configuration keys

Define all constants and configuration keys used throughout the integration.

- **Files**:
  - `custom_components/energy_optimizer/const.py` - Constants definition
- **Content Structure**:
  ```python
  DOMAIN = "energy_optimizer"
  
  # Config flow steps
  CONF_PRICE_SENSOR = "price_sensor"
  CONF_AVERAGE_PRICE_SENSOR = "average_price_sensor"
  CONF_BATTERY_SOC_SENSOR = "battery_soc_sensor"
  CONF_BATTERY_POWER_SENSOR = "battery_power_sensor"
  CONF_BATTERY_CAPACITY_AH = "battery_capacity_ah"
  CONF_BATTERY_VOLTAGE = "battery_voltage"
  CONF_BATTERY_EFFICIENCY = "battery_efficiency"
  CONF_MIN_SOC = "min_soc"
  CONF_MAX_SOC = "max_soc"
  CONF_TARGET_SOC_ENTITY = "target_soc_entity"
  
  # Default values
  DEFAULT_BATTERY_CAPACITY_AH = 200
  DEFAULT_BATTERY_VOLTAGE = 48
  DEFAULT_BATTERY_EFFICIENCY = 95
  DEFAULT_MIN_SOC = 10
  DEFAULT_MAX_SOC = 100
  
  # Services
  SERVICE_CALCULATE_CHARGE_SOC = "calculate_charge_soc"
  SERVICE_CALCULATE_SELL_ENERGY = "calculate_sell_energy"
  SERVICE_ESTIMATE_HEAT_PUMP = "estimate_heat_pump_usage"
  SERVICE_OPTIMIZE_SCHEDULE = "optimize_battery_schedule"
  ```
- **Success**:
  - All configuration keys defined as constants
  - Default values match research specifications
  - Service names match architecture documentation
- **Research References**:
  - #file:../research/20241219-config-flow-specification.md (Lines 50-115) - Configuration keys and defaults
  - #file:../research/20241219-architecture-summary.md (Lines 368-425) - Service specifications
- **Dependencies**:
  - Task 1.1 completion

### Task 1.4: Create __init__.py with integration entry points

Implement integration setup, teardown, and service registration.

- **Files**:
  - `custom_components/energy_optimizer/__init__.py` - Integration entry point
- **Key Functions**:
  - `async_setup_entry(hass, entry)` - Initialize integration from config entry
  - `async_unload_entry(hass, entry)` - Clean up on removal
  - `async_register_services(hass)` - Register all services (called once)
  - `async_reload_entry(hass, entry)` - Handle config updates
- **Success**:
  - Integration loads without errors
  - Sensor platform forwards correctly
  - Services register once (not per config entry)
  - Proper cleanup on unload
- **Research References**:
  - #file:../research/20241219-energy-optimizer-hacs-migration-research.md (Lines 565-580) - Integration setup patterns
  - #file:../research/20241219-architecture-summary.md (Lines 368-425) - Service registration requirements
- **Dependencies**:
  - Tasks 1.1-1.3 completion (structure and constants)

## Phase 2: Configuration Flow Implementation

### Task 2.1: Implement config_flow.py base structure with FlowHandler

Create config flow handler base with step management and validation helpers.

- **Files**:
  - `custom_components/energy_optimizer/config_flow.py` - Config flow handler
- **Class Structure**:
  ```python
  class EnergyOptimizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
      VERSION = 1
      
      async def async_step_user(self, user_input=None)
      async def async_step_price_entities(self, user_input=None)
      async def async_step_battery_sensors(self, user_input=None)
      async def async_step_battery_params(self, user_input=None)
      async def async_step_control_entities(self, user_input=None)
      async def async_step_pv_forecast(self, user_input=None)
      async def async_step_load_config(self, user_input=None)
      async def async_step_heat_pump(self, user_input=None)
      async def async_step_review(self, user_input=None)
      
      async def _validate_entity_state(self, entity_id, expected_domain=None)
      async def _is_numeric_state(self, state)
  ```
- **Success**:
  - FlowHandler class properly configured with DOMAIN
  - All step methods defined
  - Helper validation methods implemented
- **Research References**:
  - #file:../research/20241219-config-flow-specification.md (Lines 1-50) - Config flow design principles
  - #file:../research/20241219-architecture-summary.md (Lines 158-246) - Config flow steps overview
- **Dependencies**:
  - Phase 1 completion (constants and structure)

### Task 2.2: Implement Step 1-2 (Introduction & Price Entity Selection)

Implement initial welcome step and price entity selection with EntitySelector.

- **Files**:
  - `custom_components/energy_optimizer/config_flow.py` - Steps: user, price_entities
- **Step 1 (user)**: Display introduction with integration recommendations
- **Step 2 (price_entities)**: EntitySelector for price sensors with filters
  - Required: `price_sensor`, `average_price_sensor`
  - Optional: `cheapest_window_sensor`, `expensive_window_sensor`, `tomorrow_price_sensor`
  - Filter: `integration="rce_pse"` (suggestion, not requirement)
  - Validation: Entity exists, numeric state for sensors, binary for binary_sensor
- **Success**:
  - Introduction displays with HACS integration recommendations
  - EntitySelector properly filters by domain and integration
  - Validation catches missing or incompatible entities
  - Error messages guide user to install ha-rce-pse
- **Research References**:
  - #file:../research/20241219-config-flow-specification.md (Lines 50-165) - Steps 1-2 specifications
  - #file:../research/20241219-ha-rce-pse-integration-guide.md (Lines 1-50) - Price sensor entity names
- **Dependencies**:
  - Task 2.1 completion (base structure)

### Task 2.3: Implement Step 3-4 (Battery Sensors & Parameters)

Implement battery sensor selection and parameter configuration.

- **Files**:
  - `custom_components/energy_optimizer/config_flow.py` - Steps: battery_sensors, battery_params
- **Step 3 (battery_sensors)**: EntitySelector for battery monitoring
  - Required: `battery_soc_sensor` (device_class=battery), `battery_power_sensor` (device_class=power)
  - Optional: `battery_voltage_sensor`, `battery_current_sensor`
  - Filter: `integration="solarman"` (suggestion)
  - Validation: Entity exists, correct device_class
- **Step 4 (battery_params)**: Number inputs for battery specifications
  - `battery_capacity_ah` (default: 200), `battery_voltage` (default: 48)
  - `battery_efficiency` (default: 95), `min_soc` (default: 10), `max_soc` (default: 100)
  - Optional: `battery_capacity_entity` (for dynamic capacity)
  - Display calculated: Battery capacity (kWh), Usable capacity (kWh)
  - Validation: Ranges (capacity 1-1000, voltage 12-400, efficiency 50-100, SOC 0-100)
- **Success**:
  - Battery sensors selected with correct device classes
  - Parameters validated within acceptable ranges
  - Calculated values displayed for user verification
- **Research References**:
  - #file:../research/20241219-config-flow-specification.md (Lines 167-325) - Steps 3-4 specifications
  - #file:../research/20241219-ha-solarman-integration-guide.md (Lines 1-80) - Battery sensor entity names
- **Dependencies**:
  - Task 2.2 completion

### Task 2.4: Implement Step 5-6 (Control Entities & Load/Forecast Config)

Implement inverter control entity selection and load/forecast sensor configuration.

- **Files**:
  - `custom_components/energy_optimizer/config_flow.py` - Steps: control_entities, load_config
- **Step 5 (control_entities)**: EntitySelector for inverter control
  - Required: `target_soc_entity` (domain=number)
  - Optional: `work_mode_entity` (domain=select), `charge_current_entity`, `discharge_current_entity`, `grid_charge_switch`
  - Filter: `integration="solarman"`
  - Validation: Target SOC entity writable via number.set_value test call
- **Step 6 (load_config)**: EntitySelector for load and forecast sensors
  - Optional: `daily_load_sensor`, `pv_forecast_today`, `pv_forecast_tomorrow`, `pv_forecast_remaining`, `pv_peak_forecast`, `weather_forecast`
  - PV sensors filter: `integration="solcast_solar"`
  - Weather filter: `domain="weather"`
- **Success**:
  - Control entities validated as writable
  - Load/forecast sensors optional but recommended
  - Missing Solcast integration doesn't block config flow
- **Research References**:
  - #file:../research/20241219-config-flow-specification.md (Lines 327-520) - Steps 5-6 specifications
  - #file:../research/20241219-solcast-pv-forecast-integration-guide.md (Lines 1-60) - PV forecast entity names
- **Dependencies**:
  - Task 2.3 completion

### Task 2.5: Implement Step 7-9 (Heat Pump, Review, Options Flow)

Implement heat pump configuration, final review, and options flow for reconfiguration.

- **Files**:
  - `custom_components/energy_optimizer/config_flow.py` - Steps: heat_pump, review; OptionsFlow class
- **Step 7 (heat_pump)**: Heat pump entity selection and COP configuration
  - `enable_heat_pump` (boolean)
  - Optional: `outside_temp_sensor`, `heat_pump_power_sensor`
  - COP curve configuration (advanced, with defaults)
- **Step 8 (review)**: Display all configured entities for final review
  - Show entity IDs and friendly names
  - Calculated values (battery capacity, usable capacity)
  - Allow back navigation to fix issues
- **OptionsFlow**: Allow reconfiguration without deleting entry
  - Reuse same step methods
  - Pre-populate with existing config values
- **Success**:
  - Heat pump configuration optional and skippable
  - Review step displays complete configuration
  - Options flow enables reconfiguration
  - Config entry created successfully
- **Research References**:
  - #file:../research/20241219-config-flow-specification.md (Lines 522-740) - Steps 7-9 specifications
  - #file:../research/20241219-architecture-summary.md (Lines 158-246) - Config flow complete workflow
- **Dependencies**:
  - Task 2.4 completion

### Task 2.6: Create strings.json with config flow translations

Create UI translation strings for config flow steps, field descriptions, and error messages.

- **Files**:
  - `custom_components/energy_optimizer/strings.json` - Translation strings
- **Content Structure**:
  ```json
  {
    "config": {
      "step": {
        "user": {"title": "Welcome", "description": "..."},
        "price_entities": {"title": "Price Entities", "data": {...}},
        ...
      },
      "error": {
        "entity_not_found": "Entity not found",
        "not_numeric": "Entity state is not numeric",
        ...
      }
    }
  }
  ```
- **Success**:
  - All config flow steps have titles and descriptions
  - All data fields have names and descriptions
  - All error codes have user-friendly messages
  - UI displays localized text correctly
- **Research References**:
  - #file:../research/20241219-config-flow-specification.md (Lines 742-850) - Translation patterns and examples
- **Dependencies**:
  - Tasks 2.1-2.5 completion (all config flow steps)

## Phase 3: Calculation Library

### Task 3.1: Create calculations/__init__.py and base utilities

Create calculation module base with shared utilities and constants.

- **Files**:
  - `custom_components/energy_optimizer/calculations/__init__.py` - Module init with exports
  - `custom_components/energy_optimizer/calculations/utils.py` - Shared utilities
- **Utilities**:
  - `safe_float(value, default=0.0)` - Safe float conversion with None handling
  - `clamp(value, min_val, max_val)` - Value clamping
  - `interpolate(x, points)` - Linear interpolation from point list
  - `is_valid_percentage(value)` - Validate 0-100 range
- **Success**:
  - All calculation modules importable from calculations package
  - Utility functions handle edge cases (None, invalid types)
  - Type hints for all functions
- **Research References**:
  - #file:../research/20241219-energy-optimizer-hacs-migration-research.md (Lines 217-275) - Calculation patterns from Jinja macros
- **Dependencies**:
  - Phase 1 completion (directory structure)

### Task 3.2: Implement calculations/battery.py (SOC conversion, reserve, space)

Convert Jinja battery calculation macros to Python functions.

- **Files**:
  - `custom_components/energy_optimizer/calculations/battery.py` - Battery calculations
- **Functions**:
  ```python
  def soc_to_kwh(soc: float, capacity_ah: float, voltage: float) -> float
  def kwh_to_soc(kwh: float, capacity_ah: float, voltage: float) -> float
  def calculate_battery_reserve(current_soc: float, min_soc: float, capacity_ah: float, voltage: float) -> float
  def calculate_battery_space(current_soc: float, max_soc: float, capacity_ah: float, voltage: float) -> float
  def calculate_usable_capacity(capacity_ah: float, voltage: float, min_soc: float, max_soc: float) -> float
  ```
- **Success**:
  - SOC ↔ kWh conversion accuracy matches Jinja implementation
  - Reserve calculation: (current_soc - min_soc) * capacity * voltage / 1000
  - Space calculation: (max_soc - current_soc) * capacity * voltage / 1000
  - Unit tests validate against known values
- **Research References**:
  - #file:../research/20241219-energy-optimizer-hacs-migration-research.md (Lines 240-275) - Battery calculation macros
  - #file:../research/20241219-architecture-summary.md (Lines 79-95) - Battery calculation examples
- **Dependencies**:
  - Task 3.1 completion (utils available)

### Task 3.3: Implement calculations/charging.py (multi-phase current, charge time)

Convert Jinja charging calculation macros to Python with multi-phase logic.

- **Files**:
  - `custom_components/energy_optimizer/calculations/charging.py` - Charging calculations
- **Functions**:
  ```python
  def calculate_charge_current(energy_kwh: float, current_soc: float, capacity_ah: float, voltage: float) -> float
  def calculate_charge_time(energy_kwh: float, current_a: float, voltage: float, efficiency: float) -> float
  def get_expected_current_multi_phase(energy_to_charge: float, current_soc: float, capacity_ah: float, voltage: float) -> float
  ```
- **Multi-Phase Logic**:
  - Phase 1 (0-70% SOC): 23A charging current
  - Phase 2 (70-90% SOC): 9A charging current
  - Phase 3 (90-100% SOC): 4A charging current
  - Calculate weighted average based on energy distribution across phases
- **Success**:
  - Multi-phase current calculation matches Jinja macro logic
  - Charge time estimation accurate within 5% of real-world measurements
  - Handles edge cases (already at target SOC, zero energy needed)
- **Research References**:
  - #file:../research/20241219-energy-optimizer-hacs-migration-research.md (Lines 277-330) - Charging current macro with phases
- **Dependencies**:
  - Task 3.2 completion (battery calculations for SOC conversion)

### Task 3.4: Implement calculations/energy.py (required energy, balance, surplus)

Convert Jinja energy calculation macros to Python with load forecasting and PV integration.

- **Files**:
  - `custom_components/energy_optimizer/calculations/energy.py` - Energy balance calculations
- **Functions**:
  ```python
  def calculate_required_energy(hourly_usage: float, hours: int, efficiency: float, margin: float = 1.1) -> float
  def calculate_usage_ratio(daily_energy: float, hours_in_period: int) -> float
  def calculate_surplus_energy(battery_reserve: float, required_energy: float, pv_forecast: float = 0) -> float
  def calculate_energy_deficit(battery_space: float, required_energy: float, pv_forecast: float = 0) -> float
  def calculate_target_soc_for_deficit(current_soc: float, deficit_kwh: float, capacity_ah: float, voltage: float, max_soc: float) -> float
  ```
- **Success**:
  - Required energy calculation includes usage, losses, heat pump, with configurable margin
  - Surplus/deficit calculations account for PV forecast when available
  - Target SOC calculation respects battery limits (min_soc, max_soc)
  - Results match Jinja template calculations
- **Research References**:
  - #file:../research/20241219-energy-optimizer-hacs-migration-research.md (Lines 332-390) - Energy calculation macros
  - #file:../research/20241219-architecture-summary.md (Lines 97-145) - Energy balance examples
- **Dependencies**:
  - Task 3.2 completion (battery calculations)

### Task 3.5: Implement calculations/heat_pump.py (temperature-based COP, consumption)

Convert Jinja heat pump estimation macros to Python with temperature-based interpolation.

- **Files**:
  - `custom_components/energy_optimizer/calculations/heat_pump.py` - Heat pump calculations
- **Functions**:
  ```python
  def interpolate_cop(temperature: float, cop_curve: list[tuple[float, float]]) -> float
  def estimate_daily_consumption(min_temp: float, max_temp: float, avg_temp: float, cop_curve: list[tuple[float, float]], base_heating_demand: float = 50) -> float
  def calculate_heating_hours(min_temp: float, max_temp: float, base_temperature: float = 18) -> int
  ```
- **Default COP Curve** (temperature °C, COP):
  ```python
  DEFAULT_COP_CURVE = [
    (-20, 2.0), (-10, 2.3), (-5, 2.6), (0, 3.0), (5, 3.5),
    (10, 4.0), (15, 4.5), (20, 5.0)
  ]
  ```
- **Success**:
  - Linear interpolation between COP curve points
  - Daily consumption estimates based on degree-days method
  - Heating hours calculation from temperature range
  - Custom COP curves supported for different heat pump models
- **Research References**:
  - #file:../research/20241219-energy-optimizer-hacs-migration-research.md (Lines 392-450) - Heat pump macro with interpolation
  - #file:../research/20241219-architecture-summary.md (Lines 427-465) - Heat pump estimation service
- **Dependencies**:
  - Task 3.1 completion (interpolate utility function)

## Phase 4: Sensor Platform

### Task 4.1: Create sensor.py with platform setup and coordinator integration

Implement sensor platform base with entity registry and state update coordination.

- **Files**:
  - `custom_components/energy_optimizer/sensor.py` - Sensor platform
- **Key Components**:
  - `async_setup_entry(hass, config_entry, async_add_entities)` - Platform setup
  - `EnergyOptimizerSensor` base class - Common sensor properties
  - State update triggers (external sensor changes, time-based updates)
- **Sensor Update Strategy**:
  - Subscribe to state changes of configured entities (price sensors, battery sensors)
  - Update calculated sensors when dependencies change
  - Optional: Coordinator for coordinated polling (if needed)
- **Success**:
  - Sensor platform loads without errors
  - Base sensor class provides common functionality
  - Sensors update when external entity states change
  - Proper device_class, state_class, unit_of_measurement set
- **Research References**:
  - #file:../research/20241219-architecture-summary.md (Lines 280-325) - Sensor platform design
- **Dependencies**:
  - Phase 2 completion (config_entry available)
  - Phase 3 completion (calculation library available)

### Task 4.2: Implement battery sensors (reserve, space, capacity)

Create sensors for battery state calculations using calculation library.

- **Files**:
  - `custom_components/energy_optimizer/sensor.py` - Battery sensor classes
- **Sensors**:
  - `BatteryReserveSensor` - Energy above min SOC (kWh)
  - `BatterySpaceSensor` - Energy to full charge (kWh)
  - `BatteryCapacitySensor` - Total battery capacity (kWh)
  - `UsableCapacitySensor` - Usable capacity between min/max SOC (kWh)
- **Properties**:
  - device_class: `energy`
  - state_class: `measurement`
  - unit_of_measurement: `kWh`
  - Updates: When battery SOC sensor changes
- **Success**:
  - Sensors display correct calculated values
  - Values update immediately when battery SOC changes
  - Sensors appear in Energy dashboard
  - Historical data tracked correctly
- **Research References**:
  - #file:../research/20241219-architecture-summary.md (Lines 280-325) - Sensor specifications
  - calculations/battery.py functions
- **Dependencies**:
  - Task 4.1 completion (sensor platform base)
  - Task 3.2 completion (battery calculations)

### Task 4.3: Implement energy balance sensors (required energy, surplus/deficit)

Create sensors for energy balance calculations with time-period awareness.

- **Files**:
  - `custom_components/energy_optimizer/sensor.py` - Energy balance sensor classes
- **Sensors**:
  - `RequiredEnergyMorningSensor` - Energy needed until 12:00 (kWh)
  - `RequiredEnergyAfternoonSensor` - Energy needed 12:00-18:00 (kWh)
  - `RequiredEnergyEveningSensor` - Energy needed 18:00-22:00 (kWh)
  - `SurplusEnergySensor` - Available surplus above requirements (kWh)
  - `EnergyDeficitSensor` - Additional energy needed (kWh)
- **Calculation Inputs**:
  - Historical load data (hourly usage from history API)
  - PV forecast (if configured)
  - Heat pump estimation (if configured)
  - Battery reserve/space (from battery sensors)
- **Success**:
  - Required energy sensors update at time-period boundaries
  - Surplus/deficit calculations accurate
  - PV forecast integration working when configured
  - Sensors provide actionable data for automations
- **Research References**:
  - #file:../research/20241219-architecture-summary.md (Lines 280-325) - Sensor specifications
  - calculations/energy.py functions
- **Dependencies**:
  - Task 4.2 completion (battery sensors)
  - Task 3.4 completion (energy calculations)

### Task 4.4: Implement heat pump estimation sensor

Create sensor for daily heat pump consumption forecast based on weather.

- **Files**:
  - `custom_components/energy_optimizer/sensor.py` - Heat pump sensor class
- **Sensor**:
  - `HeatPumpEstimationSensor` - Estimated daily consumption (kWh)
- **Attributes**:
  - `min_temperature` - Forecast minimum temperature (°C)
  - `max_temperature` - Forecast maximum temperature (°C)
  - `average_cop` - Average COP for the day
  - `heating_hours` - Estimated heating hours
  - `peak_consumption` - Peak power consumption (kW)
- **Update Schedule**:
  - Daily at 00:00 when weather forecast updates
  - On-demand when weather forecast entity changes
- **Success**:
  - Sensor displays daily kWh estimate
  - Attributes provide detailed breakdown
  - Estimation accuracy within 15% of actual consumption
  - Gracefully handles missing weather forecast
- **Research References**:
  - #file:../research/20241219-architecture-summary.md (Lines 427-465) - Heat pump service specification
  - calculations/heat_pump.py functions
- **Dependencies**:
  - Task 4.1 completion (sensor platform)
  - Task 3.5 completion (heat pump calculations)

## Phase 5: Service Implementation

### Task 5.1: Create services.yaml with service definitions

Define service schemas, descriptions, and parameters for Home Assistant UI.

- **Files**:
  - `custom_components/energy_optimizer/services.yaml` - Service definitions
- **Services to Define**:
  - `calculate_charge_soc` - Calculate optimal charge target
  - `calculate_sell_energy` - Calculate sellable surplus
  - `estimate_heat_pump_usage` - Forecast heat pump consumption
  - `optimize_battery_schedule` - Generate daily schedule
- **For Each Service**:
  - Description (user-friendly explanation)
  - Fields (parameters with types, descriptions, examples)
  - Response data structure (for return values)
- **Success**:
  - Services appear in Developer Tools > Services
  - Field descriptions and examples helpful
  - Response data documented for automation use
- **Research References**:
  - #file:../research/20241219-architecture-summary.md (Lines 368-465) - Service specifications
- **Dependencies**:
  - Phase 3 completion (calculation library for service logic)

### Task 5.2: Implement calculate_charge_soc service

Implement service to calculate optimal battery charge target based on current conditions.

- **Files**:
  - `custom_components/energy_optimizer/__init__.py` - Service registration and handler
- **Service Logic**:
  1. Read current price, average price from configured entities
  2. Read battery state (SOC, capacity, power)
  3. Calculate required energy (load + heat pump + margin)
  4. Calculate PV availability (from forecast if configured)
  5. Determine optimal target SOC considering:
     - Price favorability (charge more if cheap)
     - PV forecast (charge less if sunny)
     - Load requirements (ensure coverage)
     - Battery efficiency and limits
  6. Write target SOC to configured control entity via `number.set_value`
- **Response Data**:
  ```python
  {
    "target_soc": 95,
    "current_soc": 45,
    "required_energy_kwh": 12.5,
    "pv_forecast_kwh": 8.2,
    "estimated_cost_pln": 45.23,
    "charge_time_hours": 4.2
  }
  ```
- **Success**:
  - Service calculates accurate target SOC
  - Control entity updated via service call
  - Response data useful for automation logic
  - Handles missing optional sensors gracefully
- **Research References**:
  - #file:../research/20241219-architecture-summary.md (Lines 368-395) - calculate_charge_soc specification
  - #file:../research/20241219-architecture-summary.md (Lines 97-120) - Data flow example
- **Dependencies**:
  - Phase 3 completion (all calculation functions)
  - Task 5.1 completion (services.yaml)

### Task 5.3: Implement calculate_sell_energy service

Implement service to determine sellable battery surplus based on price and requirements.

- **Files**:
  - `custom_components/energy_optimizer/__init__.py` - Service handler for sell calculation
- **Service Logic**:
  1. Read current price, average price
  2. Check price favorability (current > average * profit_margin_threshold)
  3. Calculate battery reserve above min SOC
  4. Estimate remaining load until time period end
  5. Determine surplus available for selling
  6. If profitable and surplus available, recommend sell amount
  7. Optionally set work mode to "Selling First" if configured
- **Input Parameters**:
  - `min_profit_margin` (default: 20%) - Minimum price premium required
  - `auto_set_work_mode` (default: false) - Automatically switch to sell mode
- **Response Data**:
  ```python
  {
    "surplus_kwh": 8.5,
    "sell_recommended": true,
    "current_price": 450.5,
    "average_price": 320.2,
    "profit_margin_pct": 40.7,
    "estimated_income_pln": 38.45,
    "recommended_discharge_current": 25
  }
  ```
- **Success**:
  - Service accurately determines sellable surplus
  - Profitability check prevents unprofitable selling
  - Work mode switch optional and configurable
  - Response data enables automation decisions
- **Research References**:
  - #file:../research/20241219-architecture-summary.md (Lines 397-420) - calculate_sell_energy specification
  - #file:../research/20241219-architecture-summary.md (Lines 147-175) - Selling decision flow example
- **Dependencies**:
  - Phase 3 completion (energy calculations)
  - Task 5.2 completion (service registration pattern)

### Task 5.4: Implement estimate_heat_pump_usage service

Implement service for daily heat pump consumption forecasting.

- **Files**:
  - `custom_components/energy_optimizer/__init__.py` - Service handler for heat pump estimation
- **Service Logic**:
  1. Read weather forecast entity for temperature data
  2. Extract daily temperature profile (min, max, hourly if available)
  3. Apply COP curve to temperature data
  4. Calculate heating hours based on temperature
  5. Estimate daily consumption using degree-days method
  6. Return detailed breakdown with attributes
- **Input Parameters**:
  - `date` (optional, default: today) - Date to estimate
  - `custom_cop_curve` (optional) - Override default COP curve
- **Response Data**:
  ```python
  {
    "estimated_consumption_kwh": 15.3,
    "min_temperature_c": -5,
    "max_temperature_c": 2,
    "average_cop": 3.2,
    "heating_hours": 18,
    "peak_consumption_kw": 2.1
  }
  ```
- **Success**:
  - Service estimates daily consumption accurately
  - Custom COP curves supported
  - Gracefully handles missing weather data
  - Results used in energy balance calculations
- **Research References**:
  - #file:../research/20241219-architecture-summary.md (Lines 427-465) - estimate_heat_pump_usage specification
  - calculations/heat_pump.py functions
- **Dependencies**:
  - Task 3.5 completion (heat pump calculations)
  - Task 5.3 completion (service patterns)

### Task 5.5: Implement optimize_battery_schedule service

Implement comprehensive service for full-day battery schedule optimization.

- **Files**:
  - `custom_components/energy_optimizer/__init__.py` - Service handler for schedule optimization
- **Service Logic**:
  1. Fetch full-day price data (today or tomorrow)
  2. Read PV forecast for the day
  3. Analyze historical load patterns
  4. Identify optimal charge windows (cheapest hours)
  5. Identify optimal sell windows (expensive hours)
  6. Calculate target SOC for each time period
  7. Generate hourly action schedule with reasoning
- **Input Parameters**:
  - `date` (optional, default: tomorrow) - Date to optimize
  - `optimization_goal` (optional, default: "balanced") - "cost_minimize", "self_consumption", "balanced"
- **Response Data**:
  ```python
  {
    "schedule": [
      {"time": "02:00", "action": "charge", "target_soc": 95, "reason": "Cheapest window"},
      {"time": "06:00", "action": "hold", "target_soc": 95, "reason": "Morning load coverage"},
      {"time": "17:00", "action": "sell", "target_soc": 40, "reason": "Expensive window"},
      {"time": "22:00", "action": "hold", "target_soc": 40, "reason": "Night reserve"}
    ],
    "estimated_daily_cost_pln": 12.50,
    "estimated_daily_savings_pln": 35.20,
    "estimated_grid_charge_kwh": 18.5,
    "estimated_grid_sell_kwh": 12.0
  }
  ```
- **Success**:
  - Service generates complete daily schedule
  - Schedule considers all constraints (battery limits, load, PV)
  - Optimization goals affect strategy
  - Response enables automation creation
- **Research References**:
  - #file:../research/20241219-architecture-summary.md (Lines 467-510) - optimize_battery_schedule specification
  - All calculation library functions
- **Dependencies**:
  - Tasks 5.2-5.4 completion (service patterns)
  - Phase 3 completion (all calculations)

## Phase 6: Testing & Validation

### Task 6.1: Create unit tests for calculation library

Develop comprehensive unit tests for all calculation functions.

- **Files**:
  - `tests/test_battery.py` - Battery calculation tests
  - `tests/test_charging.py` - Charging calculation tests
  - `tests/test_energy.py` - Energy balance tests
  - `tests/test_heat_pump.py` - Heat pump estimation tests
- **Test Coverage**:
  - Normal operation cases
  - Edge cases (0%, 100% SOC, zero energy)
  - Invalid inputs (negative values, out of range)
  - Calculation accuracy (compare with known results)
- **Target**: >90% code coverage for calculation library
- **Success**:
  - All tests pass
  - Coverage exceeds 90%
  - Edge cases handled gracefully
  - Calculation accuracy validated against Jinja implementation
- **Research References**:
  - #file:../research/20241219-architecture-summary.md (Lines 525-550) - Testing strategy
  - All calculation library implementations
- **Dependencies**:
  - Phase 3 completion (all calculation functions)

### Task 6.2: Create integration tests with mocked entities

Develop integration tests simulating Home Assistant environment with mocked external integrations.

- **Files**:
  - `tests/test_config_flow.py` - Config flow integration tests
  - `tests/test_sensor_platform.py` - Sensor update tests
  - `tests/test_services.py` - Service call tests
- **Mocking Strategy**:
  - Mock ha-rce-pse sensors (price, windows)
  - Mock ha-solarman entities (battery, controls)
  - Mock Solcast sensors (PV forecast)
  - Simulate state changes and service calls
- **Test Scenarios**:
  - Config flow completion with valid entities
  - Sensor updates on external state changes
  - Service calls with response data validation
  - Missing integration handling
- **Success**:
  - Integration tests pass in test environment
  - Mocks accurately simulate real integrations
  - Error handling validated
  - Service responses match specifications
- **Research References**:
  - #file:../research/20241219-architecture-summary.md (Lines 552-580) - Integration testing patterns
- **Dependencies**:
  - Phase 2 completion (config flow)
  - Phase 4 completion (sensors)
  - Phase 5 completion (services)

### Task 6.3: Validate config flow with various entity configurations

Test config flow with different entity availability scenarios.

- **Files**:
  - `tests/test_config_flow_scenarios.py` - Config flow scenario tests
- **Test Scenarios**:
  - All recommended integrations installed (ha-rce-pse, ha-solarman, Solcast)
  - Only ha-rce-pse and ha-solarman (Solcast missing)
  - Alternative integrations with compatible entity structure
  - Missing entities (validation errors)
  - Invalid entity types (domain mismatch)
- **Validation Checks**:
  - EntitySelector filters work correctly
  - Validation catches incompatible entities
  - Error messages guide user appropriately
  - Optional fields skippable
- **Success**:
  - Config flow handles all scenarios gracefully
  - Helpful error messages for missing integrations
  - Alternative integrations work if compatible
  - Optional features skippable without errors
- **Research References**:
  - #file:../research/20241219-config-flow-specification.md (Lines 1-50) - Config flow design principles
  - #file:../research/20241219-architecture-summary.md (Lines 158-246) - Config flow complete workflow
- **Dependencies**:
  - Task 6.2 completion (integration test infrastructure)

## Phase 7: Documentation & HACS Compliance

### Task 7.1: Create README.md with installation and setup instructions

Write comprehensive README with installation guide, features, and quick start.

- **Files**:
  - `README.md` - Project documentation
- **Sections**:
  - Overview and features
  - Prerequisites (recommended integrations)
  - Installation via HACS
  - Configuration guide (with screenshots)
  - Entity selection examples
  - Service usage examples
  - Troubleshooting
  - Contributing guidelines
- **Success**:
  - README clear and comprehensive
  - Installation steps easy to follow
  - Screenshots show config flow
  - Examples demonstrate key features
- **Research References**:
  - #file:../research/20241219-energy-optimizer-hacs-migration-research.md (Lines 637-680) - Documentation requirements
- **Dependencies**:
  - All implementation phases complete (for accurate documentation)

### Task 7.2: Create HACS compliance files (hacs.json, info.md)

Create HACS-specific files for repository validation and marketplace listing.

- **Files**:
  - `hacs.json` - HACS repository configuration
  - `info.md` - HACS marketplace description
- **hacs.json Structure**:
  ```json
  {
    "name": "Energy Optimizer",
    "render_readme": true,
    "homeassistant": "2024.1.0"
  }
  ```
- **info.md Content**:
  - Brief description for HACS marketplace
  - Key features bulleted list
  - Link to full README
- **Success**:
  - HACS validation passes
  - Repository appears in HACS integration search
  - Marketplace description compelling
- **Research References**:
  - #file:../research/20241219-energy-optimizer-hacs-migration-research.md (Lines 117-146) - HACS requirements
- **Dependencies**:
  - Task 7.1 completion (README for reference)

### Task 7.3: Create migration guide from YAML configuration

Write detailed guide for users migrating from YAML-based configuration.

- **Files**:
  - `docs/MIGRATION.md` - Migration guide
- **Content**:
  - Why migrate (benefits of integration approach)
  - Pre-migration checklist (backup existing config)
  - Step-by-step migration process
  - Entity mapping table (YAML sensors → integration config)
  - Automation migration examples (before/after)
  - Service usage patterns (replacing YAML templates)
  - Troubleshooting common migration issues
- **Success**:
  - Users can successfully migrate without data loss
  - Entity mappings clear and accurate
  - Automation examples cover common patterns
  - Troubleshooting addresses known issues
- **Research References**:
  - #file:../research/20241219-architecture-summary.md (Lines 512-570) - Migration from YAML examples
  - Current automations.yaml, sensors.yaml, templates.yaml
- **Dependencies**:
  - All phases complete (for accurate migration instructions)

### Task 7.4: Create automation blueprint templates

Develop reusable automation blueprints for common energy optimization patterns.

- **Files**:
  - `blueprints/automation/energy_optimizer_grid_charging.yaml` - Smart grid charging blueprint
  - `blueprints/automation/energy_optimizer_grid_selling.yaml` - Smart grid selling blueprint
  - `blueprints/automation/energy_optimizer_pv_management.yaml` - PV charging management blueprint
- **Blueprint Features**:
  - User-configurable inputs (entity selection, thresholds)
  - Service call integration
  - Notification templates
  - Condition checks (price thresholds, SOC limits)
- **Success**:
  - Blueprints importable via Home Assistant UI
  - Input selectors work correctly
  - Service calls execute properly
  - Blueprints replicate key YAML automation functionality
- **Research References**:
  - #file:../research/20241219-architecture-summary.md (Lines 467-510) - Automation blueprint examples
  - Current automations.yaml (automations 10-60)
- **Dependencies**:
  - Phase 5 completion (services available)
  - Task 7.3 completion (migration patterns identified)

## Dependencies

- **Home Assistant Core**: 2024.1.0+ (EntitySelector, config_flow features)
- **Python**: 3.11+ (Home Assistant requirement)
- **Recommended External Integrations** (user installs separately):
  - ha-rce-pse (price data and windows)
  - ha-solarman (battery/inverter control)
  - Solcast Solar (PV forecast, optional)

## Success Criteria

- Integration installs via HACS without errors
- Config flow completes with entity validation
- All sensors calculate correct values
- Services return accurate results
- Unit tests >90% coverage
- Integration tests pass
- Documentation complete and accurate
- HACS validation passes
- Migration guide enables smooth transition
- Performance < 1% CPU, < 50MB memory
