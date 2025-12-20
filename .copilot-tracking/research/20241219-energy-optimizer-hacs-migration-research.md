<!-- markdownlint-disable-file -->
# Task Research Notes: Energy Optimizer HACS Integration Migration

## Architecture Decision: Entity-Based Configuration

**IMPORTANT**: Energy Optimizer **reads sensor data from user-configured entities** at runtime. It does NOT directly integrate with external APIs or hardware.

### Compatible Integration Examples

#### 1. Price Data Source (e.g., ha-rce-pse)
- **Recommended Repository**: https://github.com/Lewa-Reka/ha-rce-pse
- **Domain**: `rce_pse` (or any integration with compatible structure)
- **What Energy Optimizer Needs**:
  - Current price sensor (numeric state)
  - Average price sensor (numeric state)
  - Price window binary sensors (optional)
  - Tomorrow price sensor (optional)
- **How Energy Optimizer Uses It**:
  - User selects price sensor entities during config flow
  - Energy Optimizer reads `hass.states.get(entity_id).state`
  - No direct API calls to ha-rce-pse
  - Compatible with ANY price integration that exposes similar sensors

#### 2. Inverter Control Source (e.g., ha-solarman)
- **Recommended Repository**: https://github.com/davidrapan/ha-solarman
- **Domain**: `solarman` (or any integration with compatible structure)
- **What Energy Optimizer Needs**:
  - Battery SOC sensor (sensor entity)
  - Battery power sensor (sensor entity)
  - Target SOC control (number entity)
  - Work mode control (select entity, optional)
  - Battery capacity (number entity or config parameter)
- **How Energy Optimizer Uses It**:
  - User selects battery/control entities during config flow
  - Energy Optimizer reads sensor states
  - Energy Optimizer calls `number.set_value` / `select.select_option` services
  - No direct Modbus communication
  - Compatible with ANY inverter integration that exposes similar entities

#### 3. PV Forecast Source (e.g., Solcast, optional)
- **Recommended Repository**: https://github.com/BJReplay/ha-solcast-solar
- **Domain**: `solcast_solar` (or any integration with compatible structure)
- **What Energy Optimizer Needs**:
  - Daily forecast sensor (kWh)
  - Peak forecast sensor (kW, optional)
  - Remaining forecast sensor (kWh, optional)
- **How Energy Optimizer Uses It**:
  - User selects forecast sensor entities during config flow
  - Energy Optimizer reads sensor state and attributes
  - No direct API calls to Solcast
  - Compatible with ANY PV forecast integration that exposes similar sensors

**Energy Optimizer Integration Focus**:
- Energy balance calculations (battery reserve/space, required energy)
- Battery charging optimization (current calculation, multi-phase charging)
- Heat pump energy estimation
- Automation coordination and scheduling
- **Reads sensor states** from user-configured entities
- **Writes to control entities** via standard HA services

## Research Executed

### File Analysis
- `automations.yaml` (2220 lines)
  - **12 numbered automations** (00, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60) implementing energy optimization logic
  - Complex grid charge/sell scheduling based on RCE pricing
  - Battery management (SOC optimization, charging limits)
  - PV forecast integration with Solcast
  - Heat pump energy estimation and scheduling
  - Inverter control (work modes, export power, charging current)

- `python_scripts/find_prices_window_*.py`
  - Price window finding algorithms
  - **Note**: Functionality now provided by ha-rce-pse integration
  - Energy Optimizer will consume window sensors from ha-rce-pse

- `sensors.yaml`
  - Template sensors with trigger-based updates (hourly weather forecast processing)
  - Heat pump energy estimation calculations
  - **Note**: RCE price sensors now provided by ha-rce-pse integration

- `templates.yaml`
  - Template sensors with weather forecast processing
  - Heat pump estimation based on temperature forecasts
  - Jinja macro imports from custom_templates

- `custom_templates/*.jinja` (7 files)
  - `calculations.jinja`: Battery charging current calculation with multi-phase logic
  - `energy_calculations.jinja`: Usage ratio, battery reserve/space, required energy, PV forecast
  - `energy_charge_planning.jinja`: Morning/afternoon charge SOC calculations
  - `energy_sell_planing.jinja`: Morning/evening/max sell calculations
  - `heat_pump.jinja`: Temperature-based HP energy usage estimation with interpolation
  - `energy_config.jinja`: Centralized configuration (battery specs, sensor mappings)
  - `usage.jinja`: Hourly usage rate extraction from history blocks

### Code Search Results
- **Numbered automations** (12 total):
  - `00 Refresh RCE Prices Today` - Daily price refresh at midnight
  - `10 Morning grid charge enable` - 04:00 grid charging
  - `15 Morning grid charge disable` - 05:59 charging cutoff
  - `20 Morning grid sell on` - High-price morning export
  - `25 Morning grid sell off` - End morning export window
  - `30 PV battery charging limit` - Sunrise-based PV charge control
  - `35 Enable PV battery charging` - Re-enable charging after limit period
  - `40 Afternoon grid charge enable` - Low tariff afternoon charging
  - `45 Afternoon grid charge disable` - End afternoon charge window
  - `50 Evening grid sell on` - Evening high-price export
  - `55 Evening grid sell off` - End evening export window
  - `60 Night battery handling` - 22:00 battery state management

### External Research
- #fetch:"https://hacs.xyz/docs/publish/integration"
  - **Repository Structure Requirements**:
    - Must have `custom_components/<domain>/` structure
    - Single integration per repository
    - All files in `custom_components/<domain>/`
  - **Manifest Requirements**: domain, documentation, issue_tracker, codeowners, name, version
  - **Home Assistant Brands**: Integration must be added to home-assistant/brands
  - **GitHub Releases**: Optional but recommended for versioning

- #fetch:"https://developers.home-assistant.io/docs/creating_integration_manifest"
  - **Integration Types**: hub, service, device, helper, entity
  - **Config Flow**: Required for modern integrations (`config_flow: true`)
  - **Dependencies**: List other HA integrations required
  - **IoT Class**: local_polling, local_push, cloud_polling, cloud_push, calculated
  - **Quality Scale**: Bronze tier minimum (silver/gold/platinum for better UX)
  - **Requirements**: Python packages on PyPI

- #fetch:"https://developers.home-assistant.io/docs/integration_fetching_data"
  - **DataUpdateCoordinator**: Coordinated polling for multiple entities
  - **Update Intervals**: Configurable via `timedelta`
  - **Error Handling**: `ConfigEntryNotReady` for offline devices, `ConfigEntryAuthFailed` for auth issues
  - **Push APIs**: Use `coordinator.async_set_updated_data(data)` for event-driven updates

- #fetch:"https://developers.home-assistant.io/docs/dev_101_services"
  - **Service Registration**: Must register in `async_setup`, not per config entry
  - **Service Schema**: Use `services.yaml` for UI descriptions
  - **Entity Services**: Use `async_register_platform_entity_service` for entity-specific actions
  - **Response Data**: Services can return structured data for advanced automations

### Project Conventions
- **Configuration Files**: YAML-based with extensive Jinja2 templating
- **State Dependencies**: Heavy reliance on sensor state values and attributes
- **Device Integration**: Inverter device (ID: `c95e6820f178b0f468fc94b9da0ddfdb`) central to automation
- **External APIs**: PSE RCE pricing API, Solcast PV forecasting
- **Template Macros**: Reusable calculation logic in separate Jinja files

## Key Discoveries

### Project Structure
**Current Implementation:**
- Standalone Home Assistant configuration with YAML automations
- 12 time-sequenced automations orchestrating energy optimization
- Jinja2 template macros for complex calculations
- REST sensors for external data (RCE prices)
- Python scripts for price window calculations (missing from repository)

**Dependencies Identified:**
- **External HACS Integrations** (Recommended):
  - **ha-rce-pse** (domain: `rce_pse`)
    - Repository: https://github.com/Lewa-Reka/ha-rce-pse
    - Provides: RCE price data, statistics, custom windows, binary sensors
  - **ha-solarman** (domain: `solarman`)
    - Repository: https://github.com/davidrapan/ha-solarman
    - Provides: Inverter communication, battery sensors, control entities
    - Supports: Deye, Solis, Solax, Sofar, and other Solarman-compatible inverters
  - **Solcast PV Forecast** (domain: `solcast_solar`) - Optional
    - Repository: https://github.com/BJReplay/ha-solcast-solar
    - Provides: Daily forecasts, peak forecast/time, detailed hourly/half-hourly forecasts
    - Sensors: `sensor.solcast_pv_forecast_forecast_today`, `sensor.solcast_pv_forecast_peak_forecast_today`, etc.
- **Home Assistant Entities** (from ha-solarman): 
  - Battery sensors: `sensor.{inverter}_battery_soc`, `sensor.{inverter}_battery_power`
  - Battery capacity: `number.{inverter}_battery_capacity`
  - Control entities: `number.{inverter}_max_soc`, `select.{inverter}_work_mode`
  - Charge/discharge limits: `number.{inverter}_battery_charge_current`
- **Other Sensors**:
  - Load/usage sensors (daily, hourly history)
  - Weather forecast sensor (for heat pump estimation)

### Implementation Patterns

**Automation Logic Flow:**
1. **Price Data Collection**: External integration (ha-rce-pse) fetches pricing at 00:00, 14:00
2. **Price Window Analysis**: External integration (ha-rce-pse) calculates optimal windows
3. **Morning Charge** (04:00-06:00): Grid charge based on deficit calculations
4. **Morning Sell** (06:00+): Export surplus during high-price windows
5. **PV Management** (Sunrise): Limit charging when PV production exceeds capacity
6. **Afternoon Charge** (Low tariff hours): Grid charge for evening usage
7. **Evening Sell** (High-price evening): Export battery surplus
8. **Night Management** (22:00): Battery state optimization

**Calculation Patterns:**
```python
# Core calculations in Jinja macros:
- Battery reserve/space (SOC to kWh conversion)
- Required energy (usage projection + losses + heat pump)
- Charging current (multi-phase with voltage consideration)
- Surplus energy (PV forecast - usage - battery limits)
- Heat pump energy (temperature-based interpolation)
```

**Responsibilities:**
- **Energy balance calculations** (battery reserve/space, required energy)
- **Battery charging optimization** (current, multi-phase logic)
- **Heat pump energy estimation**
- **Automation coordination** (schedule management, state tracking)
- **Entity state reading** (via hass.states.get())
- **Entity control** (via number.set_value, select.select_option services)

**External Integration Dependencies:**
- **Price data**: Provided by ha-rce-pse (or compatible) via sensor entities
- **Price windows**: Provided by ha-rce-pse (or compatible) via binary_sensor entities
- **Battery/inverter control**: Provided by ha-solarman (or compatible) via number/select entities
- **PV forecasts**: Provided by Solcast (or compatible) via sensor entities (optional)

### Python Script Analysis

**NOTE**: Price window finding algorithms documented here for reference. The **ha-rce-pse** integration provides this functionality through configurable window sensors. Energy Optimizer will consume these sensors via entity selection during config flow.

**Price Window Finding Algorithm:**
```python
# Window size = 4 intervals (1 hour, 15-minute intervals)
# Find highest average price window for selling opportunities
window_size = 4
max_avg = 0
max_idx = 0
for i in range(len(price_list) - window_size + 1):
    if time_list[i] < start_time or time_list[i] > end_time:
        continue
    if not time_list[i].endswith(':00'):  # Only hour boundaries
        continue
    current_avg = sum(price_list[i:i + window_size]) / window_size
    if current_avg > max_avg:
        max_avg = current_avg
        max_idx = i
```

**Dynamic Window Sizing for PV Charging:**
```python
# Calculate optimal charging window based on battery capacity and PV production
average_usage = float(sensor.load_usage_history.hourly_rate) * 1.1
average_losses = float(sensor.inverter_losses_history.hourly_rate) * 1.1
pv_peek = 0.8 * float(sensor.solcast_pv_forecast_peak_forecast_today) / 1000
capacity = 20.5  # kWh
soc = int(sensor.inverter_battery)

to_charge = 1.1 * (100 - soc) * capacity / 100  # Energy needed with 10% margin
net_charging = pv_peek - average_usage - average_losses  # Net charge rate

if net_charging > 0:
    hours_to_charge = to_charge / net_charging * 1.1  # Time with 10% safety
    window_size = int(hours_to_charge * 4) + 1  # Convert to 15-min intervals
    window_size = min(window_size, 30)  # Cap at 7.5 hours
else:
    window_size = 0  # Won't charge, use PV peak time instead
```

**Timezone-Aware DateTime Creation:**
```python
def create_aware_datetime_str(date_str, time_str):
    """Create ISO datetime string with local timezone offset."""
    naive_struct = time.strptime(f"{date_str} {time_str}:00", "%Y-%m-%d %H:%M:%S")
    timestamp = time.mktime(naive_struct)
    
    local_struct = time.localtime(timestamp)
    utc_struct = time.gmtime(timestamp)
    offset_h = local_struct.tm_hour - utc_struct.tm_hour
    offset_m = local_struct.tm_min - utc_struct.tm_min
    tz_offset = f"{offset_h:+03d}:{abs(offset_m):02d}"
    
    return f"{date_str}T{time_str}:00{tz_offset}"
```

**State and Service Call Pattern:**
```python
# Create sensor with attributes
hass.states.set('sensor.highest_price_window_morning', morning_iso, {
    'friendly_name': 'Highest Price Window Morning',
    'average_price': max_avg_morn,
    'last_update': time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    'device_class': 'timestamp'
})

# Update input_datetime helper for automation triggers
hass.services.call('input_datetime', 'set_datetime', {
    'entity_id': 'input_datetime.rce_highest_window_morning',
    'datetime': morning_iso
})
```

### Complete Examples

**NOTE**: RCE pricing sensors and price window sensors are provided by external integrations.

**Battery Charging Current Calculation:****
```jinja
{% macro get_expected_current(energy_to_charge) %}
  {# Multi-phase charging logic #}
  {% set lvl1_current = 23 %}  # 0-70% SOC
  {% set lvl2_current = 9 %}   # 70-90% SOC
  {% set lvl3_current = 5 %}   # 90-100% SOC
  
  {# Calculate energy required per phase #}
  {# Determine charging time constraints #}
  {# Return optimal current for target charge time #}
  {{ (recommended_current + 0.5) | round }}
{% endmacro %}
```

**Automation Service Call Pattern:**
```yaml
- action: number.set_value
  data:
    value: '{{ expected_soc }}'
  target:
    entity_id: number.inverter_program_1_soc
```

### API and Schema Documentation

**External Integration Dependencies:**

**RCE Price Integration (External):**
- Provides sensors: `sensor.rce_prices_today`, `sensor.rce_prices_tomorrow`, `sensor.current_rce_price`
- API: PSE RCE API (`https://api.raporty.pse.pl/api/rce-pln`)
- Data structure: 15-minute interval pricing with attributes
- Update schedule: Hourly scan, forced updates at 00:00 and 14:00

**Price Window Integration (External):**
- Provides sensors: `sensor.highest_price_window_morning`, `sensor.highest_price_window_daytime`, `sensor.lowest_price_window_daytime`
- Attributes: `average_price`, `window_start`, `window_end`
- Update trigger: On RCE price sensor state changes
- Algorithm: Sliding window analysis with configurable window sizes

**Inverter Entity Schema:**
- Device ID: Hardware identifier for service calls
- Entities: `number.*`, `select.*`, `sensor.*`
- Key controls: Battery SOC programs, work modes, charging current, export power

**Solcast Integration:**
- Sensors: `sensor.solcast_pv_forecast_forecast_today/tomorrow/remaining`
- Attributes: `detailedHourly` with `period_start`, `pv_estimate`

### Configuration Examples

**Manifest.json Pattern:**
```json
{
  "domain": "energy_optimizer",
  "name": "Energy Optimizer",
  "codeowners": ["@username"],
  "config_flow": true,
  "documentation": "https://github.com/username/energy_optimizer",
  "issue_tracker": "https://github.com/username/energy_optimizer/issues",
  "requirements": [],
  "dependencies": [],
  "after_dependencies": ["rce_pse", "solarman"],
  "iot_class": "calculated",
  "quality_scale": "bronze",
  "version": "0.1.0"
}
```

**NOTE**: 
- `rce_pse`: Domain of ha-rce-pse integration (price data - recommended)
- `solarman`: Domain of ha-solarman integration (inverter control - recommended)
- `solcast_solar`: Domain of Solcast integration (PV forecasting - optional)
- `after_dependencies`: Ensures Energy Optimizer loads after these integrations
- User can configure Energy Optimizer to work with any compatible entities

**Services.yaml Example:**
```yaml
calculate_charge_soc:
  name: Calculate Charge SOC
  description: Calculate optimal battery charge target based on prices
  fields:
    start_hour:
      name: Start Hour
      description: Charging period start hour
      required: true
      selector:
        number:
          min: 0
          max: 23
    end_hour:
      name: End Hour
      description: Charging period end hour
      required: true
      selector:
        number:
          min: 0
          max: 23
```

### Technical Requirements

**Integration Architecture Components:**

1. **Config Entry Setup** (`__init__.py`):
   - Store integration configuration (battery specs, sensor IDs, device IDs)
   - Initialize coordinators for data fetching
   - Set up platforms (sensor, binary_sensor, number)
   - Register services for calculations

2. **Data Coordinator** (`coordinator.py`):
   - Lightweight coordinator for calculation updates
   - Subscribe to external integration state changes
   - Coordinate sensor updates when dependencies change
   - Handle unavailable entities gracefully

3. **Config Flow** (`config_flow.py`):
   - Entity selection: Price sensors, battery sensors, control entities
   - Battery configuration: Capacity, efficiency, SOC limits
   - Optional: PV forecast sensors, weather sensors, heat pump sensors
   - Validation: Check entity availability
   - Options flow: Runtime configuration updates

4. **Sensor Platform** (`sensor.py`):
   - Battery reserve/space sensors (calculated)
   - Required energy sensors (morning/afternoon/evening)
   - Heat pump estimation sensor
   - Surplus energy calculation sensors
   - All read from configured entity IDs

5. **Number Platform** (`number.py`):
   - Target SOC configuration entities
   - Charge/discharge power limits

6. **Services** (`services.py`):
   - `calculate_charge_soc`: Compute required battery SOC
   - `calculate_sell_energy`: Compute available surplus
   - `optimize_schedule`: Generate automation schedule

7. **Calculation Library** (`calculations.py`):
   - Python implementation of Jinja macro logic
   - Battery physics calculations (SOC/kWh conversion)
   - Charging current optimization
   - Energy balance calculations

8. **Constants** (`const.py`):
   - Domain definition
   - Configuration keys
   - Default values (battery efficiency, safety factors)
   - Service names

**Migration Considerations:**

1. **External Integration Dependencies**:
   - Price data and windows provided by ha-rce-pse (or compatible)
   - Battery/inverter control provided by ha-solarman (or compatible)
   - PV forecasts provided by Solcast (or compatible, optional)

2. **Automation Replacement Strategy**:
   - Convert time-based triggers to coordinator-managed schedules (or blueprint templates)
   - Replace Jinja templates with Python calculation functions
   - Use event bus for state change propagation
   - Subscribe to external integration sensor updates
   - Consider blueprints for user-customizable automation

3. **State Management**:
   - Store optimization state in integration data
   - Use entity attributes for detailed calculation results
   - Implement restore state for persistence across restarts

4. **Device Integration**:
   - Inverter control via existing number/select entities
   - No direct device API needed (leverage HA entities)
   - Consider creating device registry entry for grouping
   - Entity state monitoring and service calls only

## ha-rce-pse Sensor Mapping

### Existing RCE Sensors → ha-rce-pse Sensors

| Current Sensor (old) | ha-rce-pse Sensor | Notes |
|---------------------|-------------------|-------|
| `sensor.rce_prices_today` | `sensor.rce_pse_price` | Full daily prices in `attributes.prices` |
| `sensor.current_rce_price` | `sensor.rce_pse_price` | State contains current price |
| `sensor.rce_prices_tomorrow` | `sensor.rce_pse_tomorrow_price` | Full daily prices in `attributes.prices`, available after 14:00 CET |
| N/A (Python script) | `sensor.rce_pse_today_cheapest_window_start` | Configurable via integration settings |
| N/A (Python script) | `sensor.rce_pse_today_cheapest_window_end` | Duration, start/end hour configurable |
| N/A (Python script) | `sensor.rce_pse_today_expensive_window_start` | Configurable window for highest prices |
| N/A (Python script) | `sensor.rce_pse_today_expensive_window_end` | Can replace morning/daytime highest windows |
| N/A (Python script) | `sensor.rce_pse_tomorrow_cheapest_window_start` | Tomorrow's cheapest window |
| N/A (Python script) | `sensor.rce_pse_tomorrow_expensive_window_start` | Tomorrow's expensive window |

### Binary Sensors for Window Detection

| Purpose | ha-rce-pse Binary Sensor | Usage |
|---------|-------------------------|-------|
| Active min price window | `binary_sensor.rce_pse_today_min_price_window_active` | Automation triggers |
| Active max price window | `binary_sensor.rce_pse_today_max_price_window_active` | Automation triggers |
| Custom cheapest window active | `binary_sensor.rce_pse_today_cheapest_window_active` | Configurable duration |
| Custom expensive window active | `binary_sensor.rce_pse_today_expensive_window_active` | Configurable duration |

### Statistics Sensors

Available directly from ha-rce-pse (no need to calculate):
- `sensor.rce_pse_today_average_price`
- `sensor.rce_pse_today_max_price`
- `sensor.rce_pse_today_min_price`
- `sensor.rce_pse_today_median_price`
- `sensor.rce_pse_tomorrow_average_price`
- `sensor.rce_pse_tomorrow_max_price`
- `sensor.rce_pse_tomorrow_min_price`
- `sensor.rce_pse_tomorrow_median_price`
- `sensor.rce_pse_price_comparison_to_today_average` (%)
- `sensor.rce_pse_price_comparison_to_tomorrow_average` (%)

### Time Range Sensors

- `sensor.rce_pse_today_max_price_hour_start`
- `sensor.rce_pse_today_max_price_hour_end`
- `sensor.rce_pse_today_min_price_hour_start`
- `sensor.rce_pse_today_min_price_hour_end`
- `sensor.rce_pse_today_max_price_hour_range` (e.g., "17:00 - 18:00")
- `sensor.rce_pse_today_min_price_hour_range`

### Configuration Required in ha-rce-pse

To replicate current functionality, configure:
1. **Cheapest Hours Search**:
   - Search start hour: `00:00` (for full day search)
   - Search end hour: `23:59`
   - Duration hours: Variable based on PV capacity (e.g., 3-6 hours)
   
2. **Expensive Hours Search**:
   - Search start hour: `06:00` (for morning window)
   - Search end hour: `20:00` (for daytime window)
   - Duration hours: 1-2 hours (for sell windows)

3. **Other Settings**:
   - Enable hourly price averaging: Optional (if need hourly precision)

## Recommended Approach

**Single Integrated Solution: HACS Custom Integration**

Create a comprehensive HACS integration that combines:
- **Sensors**: RCE pricing, battery metrics, energy calculations, heat pump estimates
├── calculations/            # Calculation modules
│   ├── __init__.py
│   ├── battery.py           # Battery physics and SOC calculations
│   ├── energy.py            # Energy balance and forecasting
│   ├── charging.py          # Charging current optimization
│   ├── heat_pump.py         # Heat pump energy estimation
│   └── price_windows.py     # Price window finding and dynamic sizing
custom_components/energy_optimizer/
├── __init__.py              # Integration setup, service registration
├── manifest.json            # Integration metadata
├── config_flow.py           # UI configuration flow
├── const.py                 # Constants and configuration keys
├── coordinator.py           # State update coordinator (optional, if needed)
├── sensor.py                # Sensor platform (energy calculations)
├── number.py                # Configuration entities (SOC targets, limits)
├── services.yaml            # Service definitions for UI
├── strings.json             # Translations for config flow
├── translations/            # Additional language support
│   └── en.json
└── calculations/            # Calculation modules
    ├── __init__.py
    ├── battery.py           # Battery physics and SOC calculations
    ├── energy.py            # Energy balance and forecasting
    ├── charging.py          # Charging current optimization
    └── heat_pump.py         # Heat pump energy estimation
```

**NOTE**: No `api/` directory needed - external integrations handle data fetching.

**Benefits:**
- Native Home Assistant integration with proper error handling
- UI-based configuration (no YAML editing required)
- Modular architecture with reusable external integrations
- Reusable services for custom automations
- Proper state management and persistence
- HACS distribution for easy installation and updates
- Can provide blueprint templates for common automation patterns

**Migration Path:**
1. Implement core calculation library (Python versions of Jinja macros)
2. Create config flow for sensor and device selection
3. Implement coordinator for external data (RCE prices, weather)
4. Create sensor platform with all calculation sensors
5. Implement services for on-demand calculations
6. Optional: Create blueprint automation templates
7. Document migration guide from YAML configuration

## Implementation Guidance

### Objectives
- Migrate 12 energy optimization automations to HACS-distributable integration
- Convert Jinja2 calculation templates to Python calculation library
- Implement UI-based configuration replacing YAML setup
- Provide sensors and services for energy optimization
- Maintain existing automation logic and calculation accuracy
- Enable HACS installation and automatic updates
- Depend on external integrations for price data and window analysis

### Key Tasks

1. **Project Structure Setup**:
   - Create `custom_components/energy_optimizer/` directory structure
   - Initialize `manifest.json` with proper metadata and `after_dependencies`
   - Set up `__init__.py` with integration entry points
   - Create `const.py` with domain and configuration constants

2. **Configuration Flow**:
   - Implement `config_flow.py` with multi-step setup wizard
   - Battery configuration step (capacity, efficiency, min SOC)
   - Sensor selection step (inverter, load, PV forecast, heat pump)
   - External integration check (validate RCE and price window sensors exist)
   - Tariff configuration step (times, prices) - optional if not using automations
   - Device integration step (inverter device selection)

3. **Data Coordination** (Minimal - consumes external data):
   - Create lightweight coordinator for calculation sensor updates
   - Subscribe to external integration sensor state changes
   - Update calculated sensors when dependencies change

4. **Calculation Library**:
   - Convert Jinja macros to Python in `calculations/` module
   - `battery.py`: SOC/kWh conversion, reserve/space calculations
   - `energy.py`: Required energy, usage ratio, PV forecast integration
   - `charging.py`: Multi-phase current calculation, charge time estimation
   - `heat_pump.py`: Temperature-based energy interpolation
   - Add comprehensive unit tests for all calculations

5. **Sensor Platform**:
   - Implement `sensor.py` with calculation-based sensors
   - Battery reserve/space sensors (from calculation library)
   - Required energy sensors (morning/afternoon/evening periods)
   - Heat pump estimation sensor (integrated with weather forecast)
   - Surplus/deficit calculation sensors
   - All sensors read from configured entity IDs

6. **Service Implementation**:
   - Register services in `__init__.py` `async_setup`
   - `calculate_charge_soc`: On-demand charge calculation
   - `calculate_sell_energy`: On-demand surplus calculation
   - `estimate_heat_pump_usage`: Daily consumption forecast
   - `optimize_battery_schedule`: Full day optimization
   - Service schema validation and response data

7. **Testing and Validation**:
   - Compare calculation results with existing Jinja implementation
   - Validate service responses match expected format
   - Test config flow with various sensor configurations
   - Test integration behavior when external integrations are missing
   - Validate entity state reading and service calling
   - Validate sensor updates when external sensors change state

8. **Documentation**:
   - README with installation instructions
   - **External integration setup guide** (RCE prices, price windows)
   - Configuration guide with screenshots
   - Service usage examples for automations
   - Migration guide from YAML configuration
   - Blueprint templates for common automation patterns
   - Troubleshooting guide for missing dependencies

### Dependencies
- **Recommended External Integrations (HACS)**: 
  - ha-rce-pse (price data) - **Recommended**
  - ha-solarman (inverter control) - **Recommended**
  - Solcast Solar (PV forecasting) - **Optional**
- **User Configuration**: User selects compatible entities during setup
- **Python Libraries**: Standard library only (no PyPI requirements)
- **Integration Dependencies**: `after_dependencies: ["rce_pse", "solarman"]` ensures proper load order

### Success Criteria
- Integration loads without errors in Home Assistant
- Config flow completes successfully with valid configuration
- All sensors update correctly with calculated values
- Services return accurate calculation results matching Jinja logic
- Integration passes Home Assistant quality scale bronze tier
- HACS validation passes for default repository inclusion
- Migration guide enables users to transition from YAML configuration
- Performance impact minimal (< 1% CPU, < 50MB memory)
- External integration dependencies are properly documented
