<!-- markdownlint-disable-file -->
# Energy Optimizer Architecture Summary

## Integration Dependencies

Energy Optimizer is built on a modular architecture that **reads sensor data from user-configured entities** at runtime. This design makes it compatible with any integration that exposes compatible sensor structures.

### 1. Price Data Source (e.g., ha-rce-pse)
**Recommended**: https://github.com/Lewa-Reka/ha-rce-pse  
**Domain**: `rce_pse` (or compatible)  
**Purpose**: RCE electricity price data and optimal time window calculations

**Expected Sensor Structure** (user configures entity IDs during setup):
- Current electricity price (sensor, PLN/MWh or compatible unit)
- Average price (sensor, for comparison calculations)
- Price windows (binary_sensor, for automation triggers)
- Tomorrow's prices (optional, for advanced scheduling)

**Note**: Energy Optimizer does NOT directly call ha-rce-pse APIs. It reads state from configured sensor entities.

### 2. Inverter Control Source (e.g., ha-solarman)
**Recommended**: https://github.com/davidrapan/ha-solarman  
**Domain**: `solarman` (or compatible)  
**Purpose**: Inverter and battery monitoring and control via Modbus

**Expected Entity Structure** (user configures entity IDs during setup):
- Battery SOC sensor (sensor, % or compatible)
- Battery power sensor (sensor, W or kW)
- Battery capacity (number entity or config parameter)
- Target SOC control (number entity, for setting charge target)
- Work mode control (select entity, for mode switching)
- Charge/discharge limits (number entities, optional)

**Note**: Energy Optimizer does NOT communicate with inverter hardware. It writes values to configured number/select entities.

### 3. PV Forecast Source (Optional - e.g., Solcast)
**Recommended**: https://github.com/BJReplay/ha-solcast-solar  
**Domain**: `solcast_solar` (or compatible)  
**Purpose**: Solar PV production forecasting using Solcast API

**Expected Sensor Structure** (user configures entity IDs during setup):
- Daily forecast (sensor, kWh expected today/tomorrow)
- Peak forecast (sensor, kW peak power expected)
- Remaining forecast (sensor, kWh remaining today)
- Detailed forecast attributes (optional, for hourly breakdown)

**Note**: Energy Optimizer does NOT call Solcast API. It reads state and attributes from configured forecast sensor entities.

**Used for**: Dynamic charging window sizing, surplus energy calculations, PV-aware optimization

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER INTERFACE                            │
│  Home Assistant Dashboard + Automation Blueprints + Services    │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ↓ Configuration & Triggers
┌─────────────────────────────────────────────────────────────────┐
│                    ENERGY OPTIMIZER INTEGRATION                  │
│                      (This Custom Integration)                   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Config Flow                                              │   │
│  │ - Entity selection (price sensors, battery sensors)     │   │
│  │ - Control entity selection (target SOC, work mode)      │   │
│  │ - Battery configuration (capacity, efficiency, limits)  │   │
│  │ - PV forecast configuration (optional)                  │   │
│  │ - Heat pump configuration (optional)                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Calculation Library (Python)                            │   │
│  │ - Battery: SOC ↔ kWh, reserve, space, required energy │   │
│  │ - Charging: Multi-phase current, charge time            │   │
│  │ - Heat pump: Temperature-based COP interpolation        │   │
│  │ - Energy balance: Load prediction, surplus/deficit      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Sensor Platform                                          │   │
│  │ - Battery reserve (kWh above min SOC)                   │   │
│  │ - Battery space (kWh to full charge)                    │   │
│  │ - Required energy (morning/afternoon/evening)           │   │
│  │ - Heat pump estimation (daily kWh)                      │   │
│  │ - Surplus/deficit calculations                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Service Platform                                         │   │
│  │ - calculate_charge_soc: Optimal SOC based on prices     │   │
│  │ - calculate_sell_energy: Surplus energy to sell         │   │
│  │ - estimate_heat_pump_usage: Daily consumption forecast  │   │
│  │ - optimize_battery_schedule: Full day optimization      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
└──────┬────────────────────────────────────────────────┬─────────┘
       │                                                │
       │ Reads price data                               │ Controls inverter
       ↓                                                ↓
┌──────────────────────┐                    ┌──────────────────────┐
│   ha-rce-pse         │                    │   ha-solarman        │
│   Integration        │                    │   Integration        │
│                      │                    │                      │
│ Sensors:             │                    │ Sensors:             │
│ - rce_pse_price      │                    │ - battery_soc        │
│ - today_avg_price    │                    │ - battery_power      │
│ - cheapest_window_*  │                    │ - battery_current    │
│                      │                    │                      │
│ Binary Sensors:      │                    │ Controls:            │
│ - cheapest_window_   │                    │ - max_soc (number)   │
│   active             │                    │ - charge_current     │
│ - expensive_window_  │                    │   (number)           │
│   active             │                    │ - work_mode (select) │
└──────┬───────────────┘                    └──────┬───────────────┘
       │                                            │
       │ REST API                                   │ Modbus TCP
       ↓                                            ↓
┌──────────────────────┐                    ┌──────────────────────┐
│   PSE RCE API        │                    │   Solarman Logger    │
│   (Polish Energy     │                    │   + Inverter         │
│    Market)           │                    │   (Deye/Solis/etc.)  │
└──────────────────────┘                    └──────────────────────┘
```

## Data Flow Examples

### Example 1: Morning Grid Charging Decision

```
1. Trigger: Time 06:00 or ha-rce-pse cheapest_window_active turns ON

2. Energy Optimizer reads (using configured entity IDs):
   - hass.states.get(config.price_sensor).state → current price
   - hass.states.get(config.average_price_sensor).state → average price
   - hass.states.get(config.battery_soc_sensor).state → current SOC %
   - config.battery_capacity_ah → from user config or number entity
   - hass.states.get(config.pv_forecast_sensor).state → today's forecast [optional]

3. Energy Optimizer calculates:
   - Battery reserve above min SOC
   - Required energy for morning period (based on historical usage)
   - Heat pump estimated consumption (if configured)
   - PV production forecast availability
   - Optimal target SOC considering:
     * Current price vs average
     * Cheapest window duration
     * Available battery space
     * Expected load before next cheap window

4. Energy Optimizer writes (using configured entity IDs):
   - await hass.services.async_call("number", "set_value", {
       "entity_id": config.target_soc_entity,
       "value": calculated_target_soc
     })
   - await hass.services.async_call("select", "select_option", {
       "entity_id": config.work_mode_entity,
       "option": "Battery First"
     })

5. Inverter integration (e.g., ha-solarman) responds:
   - Receives service call
   - Communicates with inverter hardware (e.g., Modbus WRITE)
   - Updates sensor entities with new states

6. Inverter hardware responds:
   - Begins grid charging to target SOC
   - Battery power sensor updates (goes negative during charging)
```

### Example 2: Evening Grid Selling Decision

```
1. Trigger: ha-rce-pse expensive_window_active turns ON

2. Energy Optimizer reads (using configured entity IDs):
   - hass.states.get(config.price_sensor).state → current price
   - hass.states.get(config.average_price_sensor).state → average price
   - hass.states.get(config.battery_soc_sensor).state → current SOC
   - hass.states.get(config.battery_power_sensor).state → current power
   - Historical evening load pattern (from history API)

3. Energy Optimizer calculates:
   - Available battery energy above reserve
   - Evening load requirements until bedtime
   - Surplus energy that can be sold
   - Profitability threshold (current price > X% of average)

4. Energy Optimizer decides:
   - IF surplus > 2 kWh AND price > 120% avg:
     - SELL surplus to grid
   - ELSE:
     - HOLD battery for self-consumption

5. Energy Optimizer writes (if profitable):
   - Service call: select.select_option → "Selling First"
   - Service call: number.set_value → discharge current limit

6. Inverter integration and hardware respond:
   - Inverter exports surplus to grid during expensive window
   - Sensor entities update with export power (positive battery_power)
   - Stops when surplus depleted or window ends
```

### Example 3: Dynamic PV Charging Window Sizing

```
1. Trigger: Time 14:00 (when tomorrow's RCE prices available)
2. Energy Optimizer reads (using configured entity IDs):
   - hass.states.get(config.tomorrow_price_sensor).state → tomorrow prices
   - hass.states.get(config.pv_forecast_sensor).state → tomorrow PV forecast
   - config.battery_capacity, config.battery_efficiency → from user config

3. Energy Optimizer calculates:
   - If PV forecast < 5 kWh: Need 6-hour charge window
   - If PV forecast 5-10 kWh: Need 4-hour window
   - If PV forecast > 10 kWh: Need 3-hour window (PV will supplement)

4. Energy Optimizer updates:
   - Reconfigure ha-rce-pse window search duration (if API available)
   - OR create automation template selecting appropriate window sensor
   - OR store window size for next morning's automation

5. Next morning automation uses:
   - Appropriately sized window based on PV forecast
   - Energy Optimizer calculates target SOC accordingly
```

## Responsibilities Matrix

| Functionality | Implementation | Provided By |
|--------------|----------------|-------------|
| **RCE Price Fetching** | REST API to PSE | Price integration (e.g., ha-rce-pse) |
| **Price Statistics** | Average, min, max calculation | Price integration (e.g., ha-rce-pse) |
| **Price Window Finding** | Configurable window search | Price integration (e.g., ha-rce-pse) |
| **Binary Window Sensors** | Active window detection | Price integration (e.g., ha-rce-pse) |
| **Inverter Communication** | Modbus TCP protocol | Inverter integration (e.g., ha-solarman) |
| **Battery Monitoring** | SOC, power, voltage sensors | Inverter integration (e.g., ha-solarman) |
| **Inverter Control** | Number/select entities | Inverter integration (e.g., ha-solarman) |
| **Work Mode Management** | Mode selection | Inverter integration (e.g., ha-solarman) |
| **Entity State Reading** | hass.states.get() | Energy Optimizer |
| **Entity Service Calls** | number.set_value, select.select_option | Energy Optimizer |
| **Battery Calculations** | SOC ↔ kWh, reserve, space | Energy Optimizer |
| **Charging Optimization** | Multi-phase current calc | Energy Optimizer |
| **Heat Pump Estimation** | COP-based consumption | Energy Optimizer |
| **Energy Balance** | Load prediction, surplus | Energy Optimizer |
| **Automation Coordination** | Services + blueprints | Energy Optimizer |
| **PV Forecasting** | Solar production estimate | Solcast Solar (optional) |

## Configuration Flow

### Step 1: Entity Availability Check
```
Energy Optimizer Config Flow:
1. Verify price sensors exist in Home Assistant
   - At least one sensor with numeric state (for current price)
   - Recommend filtering by integration=rce_pse for convenience
2. Verify battery sensors exist in Home Assistant
   - At least one sensor with battery device_class (for SOC)
   - At least one number entity (for control)
3. Show helpful guidance if no compatible entities found:
   - "No price sensors found. Consider installing ha-rce-pse from HACS."
   - "No battery sensors found. Consider installing ha-solarman from HACS."
4. Allow user to proceed with manual entity selection
```

### Step 2: Price Entity Configuration
```
Entity Selection (user chooses from available entities):

Required:
- Current price sensor [selector: domain=sensor]
  Example: sensor.rce_pse_price or sensor.electricity_price
  
- Average price sensor [selector: domain=sensor]
  Example: sensor.rce_pse_today_average_price

Optional:
- Cheapest window sensor [selector: domain=binary_sensor]
  Example: binary_sensor.rce_pse_today_cheapest_window_active
  
- Expensive window sensor [selector: domain=binary_sensor]
  Example: binary_sensor.rce_pse_today_expensive_window_active
  
- Tomorrow price sensor [selector: domain=sensor]
  Example: sensor.rce_pse_tomorrow_price
```

### Step 3: Battery Entity Configuration
```
Entity Selection (user chooses from available entities):

Required:
- Battery SOC sensor [selector: domain=sensor, device_class=battery]
  Example: sensor.deye_hybrid_battery_soc
  
- Battery power sensor [selector: domain=sensor, device_class=power]
  Example: sensor.deye_hybrid_battery_power

Battery Parameters:
- Battery capacity (Ah) [numeric input, read from number entity if available]
- Battery voltage (V) [default: 48]
- Battery efficiency (%) [default: 95]
- Minimum SOC (%) [default: 10]
- Maximum SOC (%) [default: 100]
```

### Step 4: Control Entity Selection
```
Entity Selection (user chooses from available entities):

Required:
- Target SOC control [selector: domain=number]
  Example: number.deye_hybrid_max_soc or number.inverter_target_soc
  Purpose: Energy Optimizer writes calculated target SOC here

Optional:
- Work mode control [selector: domain=select]
  Example: select.deye_hybrid_work_mode
  Purpose: Switch between Battery First, Selling First, etc.
  
- Charge current limit [selector: domain=number]
  Example: number.deye_hybrid_battery_charge_current
  
- Discharge current limit [selector: domain=number]
  Example: number.deye_hybrid_battery_discharge_current
  
- Grid charge enable [selector: domain=switch]
  Example: switch.deye_hybrid_grid_charge
```

### Step 5: Load & Forecast Configuration
```
Entity Selection (all optional):

- Daily load sensor [selector: domain=sensor, device_class=energy]
  Example: sensor.home_energy_consumption
  Purpose: For load pattern analysis
  
- PV forecast sensor [selector: domain=sensor]
  Example: sensor.solcast_pv_forecast_today
  Purpose: Dynamic charge window sizing, surplus calculation
  
- PV remaining sensor [selector: domain=sensor]
  Example: sensor.solcast_pv_forecast_forecast_remaining_today
  Purpose: Real-time surplus/deficit calculation
  
- Weather forecast [selector: domain=weather]
  Example: weather.home
  Purpose: Heat pump consumption estimation
```

### Step 6: Heat Pump Configuration (Optional)
```
Enable heat pump estimation [boolean]

IF enabled, entity selection:
- Outside temperature sensor [selector: domain=sensor, device_class=temperature]
  Example: sensor.outside_temperature
  Purpose: COP calculation input
  
- Heat pump power sensor [selector: domain=sensor, device_class=power]
  Example: sensor.heat_pump_power
  Purpose: Historical consumption analysis (optional)

COP Curve Configuration [advanced]:
- Temperature-to-COP mapping table
- Default interpolation curve provided
- User can customize per their heat pump model
```

## Services Provided

### 1. `energy_optimizer.calculate_charge_soc`

**Purpose**: Calculate optimal battery charge target based on current prices and conditions

**Input**:
- `battery_soc_sensor` (optional, uses config default)
- `target_soc_number` (optional, uses config default)
- `force_calculation` (boolean, default: false)

**Processing**:
1. Read price data from configured entities (current, average)
2. Read battery state from configured entities (SOC, capacity, power)
3. Calculate required energy (load forecast + heat pump)
4. Calculate optimal SOC considering:
   - Price vs average (charge more if cheap)
   - PV forecast (charge less if sunny)
   - Load requirements (ensure coverage)
   - Battery efficiency (account for losses)
5. Write to configured target SOC entity via number.set_value service

**Output**:
```yaml
target_soc: 95
current_soc: 45
cheapest_window_start: "2024-12-19T02:00:00"
cheapest_window_end: "2024-12-19T06:00:00"
expected_charge_kwh: 12.5
estimated_cost_pln: 45.23
```

### 2. `energy_optimizer.calculate_sell_energy`

**Purpose**: Determine how much surplus battery energy can be profitably sold

**Input**:
- `battery_soc_sensor` (optional)
- `min_profit_margin` (%, default: 20)

**Processing**:
1. Read price data from configured entities (current vs average)
2. Read battery state from configured entities
3. Calculate available surplus above reserve
4. Calculate evening load requirements
5. Determine sell amount if profitable

**Output**:
```yaml
surplus_kwh: 8.5
sell_recommended: true
current_price: 450.5
average_price: 320.2
profit_margin_pct: 40.7
estimated_income_pln: 38.45
recommended_discharge_current: 25
```

### 3. `energy_optimizer.estimate_heat_pump_usage`

**Purpose**: Forecast daily heat pump energy consumption

**Input**:
- `date` (optional, default: today)
- `weather_forecast` (optional, uses config default)

**Processing**:
1. Read weather forecast (temperature profile)
2. Apply COP curve (temperature → efficiency)
3. Estimate heating demand (degree-days method)
4. Calculate expected consumption (kWh)

**Output**:
```yaml
estimated_consumption_kwh: 15.3
average_cop: 3.2
min_temperature_c: -5
max_temperature_c: 2
heating_hours: 18
peak_consumption_kw: 2.1
```

### 4. `energy_optimizer.optimize_battery_schedule`

**Purpose**: Create full-day battery schedule based on prices and forecasts

**Input**:
- `date` (optional, default: tomorrow)
- `optimization_goal` (cost_minimize | self_consumption | balanced)

**Processing**:
1. Read full-day price data from configured entities
2. Read PV forecast from configured entities (if configured)
3. Read load pattern history from Home Assistant history API
4. Calculate optimal charge/discharge schedule
5. Return hourly actions

**Output**:
```yaml
schedule:
  - time: "02:00"
    action: "charge"
    target_soc: 95
    reason: "Cheapest window"
  - time: "06:00"
    action: "hold"
    target_soc: 95
    reason: "Morning load coverage"
  - time: "17:00"
    action: "sell"
    target_soc: 40
    reason: "Expensive window"
  - time: "22:00"
    action: "hold"
    target_soc: 40
    reason: "Night reserve"
estimated_daily_cost_pln: 12.50
estimated_daily_savings_pln: 35.20
```

## Automation Blueprints

### Blueprint 1: Grid Charge During Cheapest Window

```yaml
blueprint:
  name: Energy Optimizer - Smart Grid Charging
  domain: automation
  input:
    cheapest_window_binary:
      name: Cheapest Window Sensor
      selector:
        entity:
          integration: rce_pse
          domain: binary_sensor
    battery_soc_sensor:
      name: Battery SOC Sensor
      selector:
        entity:
          integration: solarman
          device_class: battery
    min_soc_threshold:
      name: Minimum SOC to Trigger
      selector:
        number:
          min: 0
          max: 100
          unit_of_measurement: "%"
      default: 80

trigger:
  - platform: state
    entity_id: !input cheapest_window_binary
    to: "on"

condition:
  - condition: numeric_state
    entity_id: !input battery_soc_sensor
    below: !input min_soc_threshold

action:
  - service: energy_optimizer.calculate_charge_soc
    response_variable: charge_plan
  - service: notify.persistent_notification
    data:
      title: "Battery Charging Started"
      message: "Target SOC: {{ charge_plan.target_soc }}% | Expected cost: {{ charge_plan.estimated_cost_pln }} PLN"
```

### Blueprint 2: Grid Sell During Expensive Window

```yaml
blueprint:
  name: Energy Optimizer - Smart Grid Selling
  domain: automation
  input:
    expensive_window_binary:
      name: Expensive Window Sensor
      selector:
        entity:
          integration: rce_pse
          domain: binary_sensor
    min_profit_margin:
      name: Minimum Profit Margin
      selector:
        number:
          min: 0
          max: 100
          unit_of_measurement: "%"
      default: 20

trigger:
  - platform: state
    entity_id: !input expensive_window_binary
    to: "on"

action:
  - service: energy_optimizer.calculate_sell_energy
    data:
      min_profit_margin: !input min_profit_margin
    response_variable: sell_plan
  - choose:
      - conditions:
          - condition: template
            value_template: "{{ sell_plan.sell_recommended }}"
        sequence:
          - service: select.select_option
            target:
              entity_id: select.deye_hybrid_work_mode
            data:
              option: "Selling First"
          - service: notify.persistent_notification
            data:
              title: "Battery Selling Started"
              message: "Surplus: {{ sell_plan.surplus_kwh }} kWh | Expected income: {{ sell_plan.estimated_income_pln }} PLN"
```

## Migration from YAML

### Old YAML Automation
```yaml
automation:
  - id: '00_rce_znajdz_okna_cenowe'
    alias: '00 RCE znajdź okna cenowe'
    trigger:
      - platform: time
        at: '14:00:00'
    action:
      - service: python_script.find_prices_window_daytime
        data:
          prices_entity: sensor.rce_prices_tomorrow
          
  - id: '10_grid_charge_morning'
    alias: '10 Grid Charge - Morning'
    trigger:
      - platform: template
        value_template: "{{ now().strftime('%H:%M') == states('input_datetime.rce_lowest_window_noon')[0:5] }}"
    action:
      - service: number.set_value
        target:
          entity_id: number.inverter_max_soc
        data:
          value: 100
```

### New Energy Optimizer Approach
```yaml
automation:
  # No need for price window finding - ha-rce-pse does this automatically

  - id: 'energy_optimizer_grid_charge'
    alias: 'Energy Optimizer - Smart Grid Charging'
    trigger:
      - platform: state
        entity_id: binary_sensor.rce_pse_today_cheapest_window_active
        to: 'on'
    action:
      - service: energy_optimizer.calculate_charge_soc
        response_variable: charge_plan
      # Target SOC automatically set by service to ha-solarman entity
```

**Benefits**:
- ✅ No Python scripts to maintain
- ✅ No manual time triggers
- ✅ No input_datetime helpers needed
- ✅ Direct binary sensor triggers from ha-rce-pse
- ✅ Automatic calculation and entity updates
- ✅ Response data for notifications

## Testing Strategy

### Unit Tests
```python
# Test calculation library
def test_battery_reserve_calculation():
    """Test battery reserve above min SOC."""
    result = calculate_battery_reserve(
        current_soc=60, 
        capacity_ah=200, 
        voltage=48, 
        min_soc=10
    )
    assert result == 48.0  # (60-10)% * 200Ah * 48V / 1000
```

### Integration Tests
```python
# Test with mocked integrations
async def test_charge_soc_service(hass, mock_rce_pse, mock_solarman):
    """Test calculate_charge_soc service."""
    # Mock ha-rce-pse sensors
    mock_rce_pse.set_price(250.5)
    mock_rce_pse.set_average_price(320.0)
    
    # Mock ha-solarman sensors
    mock_solarman.set_battery_soc(45)
    mock_solarman.set_battery_capacity(200)
    
    # Call service
    response = await hass.services.async_call(
        "energy_optimizer",
        "calculate_charge_soc",
        blocking=True,
        return_response=True
    )
    
    # Verify calculations
    assert response["target_soc"] > 90  # Should charge high when cheap
    assert mock_solarman.get_max_soc() == response["target_soc"]
```

## Summary

Energy Optimizer is a **coordination and calculation layer** that:

**✅ Leverages sensor entities from any compatible integration**:
- Price sensors (e.g., from ha-rce-pse or compatible)
- Battery/inverter control entities (e.g., from ha-solarman or compatible)
- PV forecast sensors (e.g., from Solcast or compatible)

**✅ Provides intelligent calculations**:
- Battery optimization algorithms
- Energy balance forecasting
- Heat pump consumption estimation

**✅ Offers automation services**:
- On-demand calculation services
- Automation blueprints
- Direct entity control

**✅ Simplifies user experience**:
- UI-based configuration
- Automatic entity discovery
- Pre-built blueprints
- Migration from YAML

**❌ Does NOT**:
- Fetch price data from external APIs (relies on price integration)
- Communicate with inverter hardware (relies on inverter integration)
- Fetch PV forecasts from external APIs (relies on forecast integration)
- Mandate specific integrations (accepts any compatible entity structure)

This architecture ensures maintainability, reliability, and community support while focusing Energy Optimizer on what it does best: **intelligent battery and energy optimization**.
