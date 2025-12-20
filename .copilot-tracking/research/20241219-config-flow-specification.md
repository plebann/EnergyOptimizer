<!-- markdownlint-disable-file -->
# Energy Optimizer Config Flow Specification

## Overview

Energy Optimizer uses an **entity-based configuration approach** where users select sensor and control entities during setup. This design ensures compatibility with any Home Assistant integration that exposes compatible entity structures.

## Design Principles

### 1. No Hard Dependencies
- Energy Optimizer does NOT require specific integrations to be installed
- Users can configure ANY entities with compatible data structures
- Recommendations guide users toward proven integrations (ha-rce-pse, ha-solarman, Solcast)
- Validation checks entity availability, not integration presence

### 2. Runtime Entity Access
```python
# Energy Optimizer reads sensor states at runtime
current_price = hass.states.get(config_entry.data["price_sensor"]).state
battery_soc = hass.states.get(config_entry.data["battery_soc_sensor"]).state

# Energy Optimizer writes to control entities via services
await hass.services.async_call(
    "number",
    "set_value",
    {
        "entity_id": config_entry.data["target_soc_entity"],
        "value": calculated_soc
    }
)
```

### 3. User-Friendly Entity Selection
- Use `EntitySelector` with appropriate filters (domain, device_class, integration)
- Provide clear descriptions and examples
- Show helper text recommending compatible integrations
- Allow manual entity ID entry if selector doesn't find suitable entities

## Configuration Flow Steps

### Step 1: Introduction & Recommendations

**Purpose**: Welcome user and provide integration recommendations

**UI Elements**:
```yaml
type: form
data_schema: {}
description: |
  Energy Optimizer coordinates battery charging and energy optimization based on electricity prices, battery state, and PV forecasts.
  
  **Recommended Integrations** (install from HACS if needed):
  - **ha-rce-pse**: RCE electricity pricing and price windows
  - **ha-solarman**: Inverter and battery control
  - **Solcast Solar**: PV production forecasting (optional)
  
  You can use other integrations with compatible entity structures.

buttons:
  - label: Continue
    action: next_step
  - label: Cancel
    action: cancel
```

### Step 2: Price Entity Configuration

**Purpose**: Select entities that provide electricity price data

**Schema**:
```python
vol.Schema({
    vol.Required("price_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            # Prefer rce_pse integration but allow any numeric sensor
            filter=selector.EntityFilterSelectorConfig(
                integration="rce_pse"  # Suggestion, not requirement
            )
        )
    ),
    vol.Required("average_price_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            filter=selector.EntityFilterSelectorConfig(
                integration="rce_pse"
            )
        )
    ),
    vol.Optional("cheapest_window_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="binary_sensor",
            filter=selector.EntityFilterSelectorConfig(
                integration="rce_pse"
            )
        )
    ),
    vol.Optional("expensive_window_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="binary_sensor",
            filter=selector.EntityFilterSelectorConfig(
                integration="rce_pse"
            )
        )
    ),
    vol.Optional("tomorrow_price_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            filter=selector.EntityFilterSelectorConfig(
                integration="rce_pse"
            )
        )
    ),
})
```

**Field Descriptions**:
```yaml
price_sensor:
  name: Current Price Sensor
  description: Sensor providing current electricity price (PLN/MWh or compatible unit)
  example: sensor.rce_pse_price
  
average_price_sensor:
  name: Average Price Sensor
  description: Sensor providing average price for comparison
  example: sensor.rce_pse_today_average_price
  
cheapest_window_sensor:
  name: Cheapest Window Sensor (Optional)
  description: Binary sensor indicating cheapest price window is active
  example: binary_sensor.rce_pse_today_cheapest_window_active
  
expensive_window_sensor:
  name: Expensive Window Sensor (Optional)
  description: Binary sensor indicating expensive price window is active
  example: binary_sensor.rce_pse_today_expensive_window_active
  
tomorrow_price_sensor:
  name: Tomorrow Price Sensor (Optional)
  description: Sensor providing tomorrow's price data (for advanced scheduling)
  example: sensor.rce_pse_tomorrow_price
```

**Validation**:
```python
async def validate_price_entities(user_input: dict) -> dict[str, str]:
    """Validate price entity configuration."""
    errors = {}
    
    # Check current price sensor exists and has numeric state
    price_state = hass.states.get(user_input["price_sensor"])
    if not price_state:
        errors["price_sensor"] = "entity_not_found"
    elif not is_numeric_state(price_state.state):
        errors["price_sensor"] = "not_numeric"
    
    # Check average price sensor
    avg_state = hass.states.get(user_input["average_price_sensor"])
    if not avg_state:
        errors["average_price_sensor"] = "entity_not_found"
    elif not is_numeric_state(avg_state.state):
        errors["average_price_sensor"] = "not_numeric"
    
    # Check optional binary sensors if provided
    if "cheapest_window_sensor" in user_input:
        window_state = hass.states.get(user_input["cheapest_window_sensor"])
        if not window_state:
            errors["cheapest_window_sensor"] = "entity_not_found"
        elif window_state.domain != "binary_sensor":
            errors["cheapest_window_sensor"] = "not_binary_sensor"
    
    return errors
```

### Step 3: Battery Sensor Configuration

**Purpose**: Select entities that monitor battery state

**Schema**:
```python
vol.Schema({
    vol.Required("battery_soc_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            device_class=SensorDeviceClass.BATTERY,
            filter=selector.EntityFilterSelectorConfig(
                integration="solarman"  # Suggestion only
            )
        )
    ),
    vol.Required("battery_power_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            device_class=SensorDeviceClass.POWER,
            filter=selector.EntityFilterSelectorConfig(
                integration="solarman"
            )
        )
    ),
    vol.Optional("battery_voltage_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            device_class=SensorDeviceClass.VOLTAGE,
            filter=selector.EntityFilterSelectorConfig(
                integration="solarman"
            )
        )
    ),
    vol.Optional("battery_current_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            device_class=SensorDeviceClass.CURRENT,
            filter=selector.EntityFilterSelectorConfig(
                integration="solarman"
            )
        )
    ),
})
```

**Field Descriptions**:
```yaml
battery_soc_sensor:
  name: Battery SOC Sensor
  description: Sensor showing battery state of charge (%)
  example: sensor.deye_hybrid_battery_soc
  required: true
  
battery_power_sensor:
  name: Battery Power Sensor
  description: Sensor showing battery charge/discharge power (W or kW)
  example: sensor.deye_hybrid_battery_power
  required: true
  note: Negative values typically indicate charging, positive indicates discharging
  
battery_voltage_sensor:
  name: Battery Voltage Sensor (Optional)
  description: Sensor showing battery voltage (V)
  example: sensor.deye_hybrid_battery_voltage
  
battery_current_sensor:
  name: Battery Current Sensor (Optional)
  description: Sensor showing battery current (A)
  example: sensor.deye_hybrid_battery_current
```

### Step 4: Battery Parameters

**Purpose**: Configure battery specifications and limits

**Schema**:
```python
vol.Schema({
    vol.Required("battery_capacity_ah", default=200): vol.All(
        vol.Coerce(float),
        vol.Range(min=1, max=1000)
    ),
    vol.Required("battery_voltage", default=48): vol.All(
        vol.Coerce(float),
        vol.Range(min=12, max=400)
    ),
    vol.Required("battery_efficiency", default=95): vol.All(
        vol.Coerce(float),
        vol.Range(min=50, max=100)
    ),
    vol.Required("min_soc", default=10): vol.All(
        vol.Coerce(int),
        vol.Range(min=0, max=100)
    ),
    vol.Required("max_soc", default=100): vol.All(
        vol.Coerce(int),
        vol.Range(min=0, max=100)
    ),
    vol.Optional("battery_capacity_entity"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="number",
            filter=selector.EntityFilterSelectorConfig(
                integration="solarman"
            )
        )
    ),
})
```

**Field Descriptions**:
```yaml
battery_capacity_ah:
  name: Battery Capacity (Ah)
  description: Battery capacity in Ampere-hours
  default: 200
  unit: Ah
  
battery_voltage:
  name: Battery Nominal Voltage (V)
  description: Battery system voltage (typically 48V for hybrid systems)
  default: 48
  unit: V
  
battery_efficiency:
  name: Battery Efficiency (%)
  description: Round-trip efficiency (charge/discharge losses)
  default: 95
  unit: "%"
  note: Typical LiFePO4 efficiency is 90-95%
  
min_soc:
  name: Minimum SOC (%)
  description: Minimum state of charge to preserve battery health
  default: 10
  unit: "%"
  
max_soc:
  name: Maximum SOC (%)
  description: Maximum state of charge (may be limited by inverter)
  default: 100
  unit: "%"
  
battery_capacity_entity:
  name: Battery Capacity Entity (Optional)
  description: Number entity to read/write battery capacity dynamically
  example: number.deye_hybrid_battery_capacity
```

**Calculated Display**:
```yaml
calculated_values:
  battery_capacity_kwh: "{{ (battery_capacity_ah * battery_voltage / 1000) | round(2) }}"
  usable_capacity_kwh: "{{ ((max_soc - min_soc) / 100 * battery_capacity_ah * battery_voltage / 1000) | round(2) }}"
  
display:
  - "Battery Capacity: {battery_capacity_kwh} kWh"
  - "Usable Capacity: {usable_capacity_kwh} kWh ({min_soc}% - {max_soc}%)"
```

### Step 5: Control Entity Configuration

**Purpose**: Select entities for controlling battery/inverter behavior

**Schema**:
```python
vol.Schema({
    vol.Required("target_soc_entity"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="number",
            filter=selector.EntityFilterSelectorConfig(
                integration="solarman"
            )
        )
    ),
    vol.Optional("work_mode_entity"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="select",
            filter=selector.EntityFilterSelectorConfig(
                integration="solarman"
            )
        )
    ),
    vol.Optional("charge_current_entity"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="number",
            filter=selector.EntityFilterSelectorConfig(
                integration="solarman"
            )
        )
    ),
    vol.Optional("discharge_current_entity"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="number",
            filter=selector.EntityFilterSelectorConfig(
                integration="solarman"
            )
        )
    ),
    vol.Optional("grid_charge_switch"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="switch",
            filter=selector.EntityFilterSelectorConfig(
                integration="solarman"
            )
        )
    ),
})
```

**Field Descriptions**:
```yaml
target_soc_entity:
  name: Target SOC Control
  description: Number entity to set battery charge target
  example: number.deye_hybrid_max_soc
  required: true
  note: Energy Optimizer will write calculated target SOC to this entity
  
work_mode_entity:
  name: Work Mode Control (Optional)
  description: Select entity to switch inverter work modes
  example: select.deye_hybrid_work_mode
  options_example: ["Battery First", "Selling First", "Zero Export", "Load First"]
  
charge_current_entity:
  name: Charge Current Limit (Optional)
  description: Number entity to limit battery charging current
  example: number.deye_hybrid_battery_charge_current
  unit: A
  
discharge_current_entity:
  name: Discharge Current Limit (Optional)
  description: Number entity to limit battery discharge current
  example: number.deye_hybrid_battery_discharge_current
  unit: A
  
grid_charge_switch:
  name: Grid Charge Enable (Optional)
  description: Switch to enable/disable grid charging
  example: switch.deye_hybrid_grid_charge
```

**Validation**:
```python
async def validate_control_entities(user_input: dict) -> dict[str, str]:
    """Validate control entity configuration."""
    errors = {}
    
    # Check target SOC entity exists and is a number
    target_entity = hass.states.get(user_input["target_soc_entity"])
    if not target_entity:
        errors["target_soc_entity"] = "entity_not_found"
    elif target_entity.domain != "number":
        errors["target_soc_entity"] = "not_number_entity"
    else:
        # Verify entity accepts values in reasonable SOC range (0-100)
        try:
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": user_input["target_soc_entity"], "value": 50},
                blocking=True,
            )
        except Exception as err:
            errors["target_soc_entity"] = "cannot_write"
    
    # Check optional work mode entity
    if "work_mode_entity" in user_input:
        mode_entity = hass.states.get(user_input["work_mode_entity"])
        if not mode_entity:
            errors["work_mode_entity"] = "entity_not_found"
        elif mode_entity.domain != "select":
            errors["work_mode_entity"] = "not_select_entity"
    
    return errors
```

### Step 6: PV Forecast Configuration (Optional)

**Purpose**: Select PV forecast entities for dynamic optimization

**Schema**:
```python
vol.Schema({
    vol.Optional("enable_pv_forecast", default=False): bool,
    vol.Optional("pv_forecast_today"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            filter=selector.EntityFilterSelectorConfig(
                integration="solcast_solar"
            )
        )
    ),
    vol.Optional("pv_forecast_tomorrow"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            filter=selector.EntityFilterSelectorConfig(
                integration="solcast_solar"
            )
        )
    ),
    vol.Optional("pv_forecast_remaining"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            filter=selector.EntityFilterSelectorConfig(
                integration="solcast_solar"
            )
        )
    ),
    vol.Optional("pv_peak_forecast"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            filter=selector.EntityFilterSelectorConfig(
                integration="solcast_solar"
            )
        )
    ),
})
```

**Conditional Display**:
```python
# Only show PV entity selectors if enable_pv_forecast is True
if user_input.get("enable_pv_forecast"):
    # Show PV entity selectors
else:
    # Skip to next step
```

**Field Descriptions**:
```yaml
enable_pv_forecast:
  name: Enable PV Forecast Integration
  description: Use PV production forecasts for dynamic optimization
  default: false
  
pv_forecast_today:
  name: Today's PV Forecast
  description: Sensor showing expected PV production today (kWh)
  example: sensor.solcast_pv_forecast_forecast_today
  
pv_forecast_tomorrow:
  name: Tomorrow's PV Forecast
  description: Sensor showing expected PV production tomorrow (kWh)
  example: sensor.solcast_pv_forecast_forecast_tomorrow
  
pv_forecast_remaining:
  name: Remaining PV Forecast
  description: Sensor showing remaining PV production today (kWh)
  example: sensor.solcast_pv_forecast_forecast_remaining_today
  
pv_peak_forecast:
  name: Peak PV Forecast
  description: Sensor showing peak PV power expected (kW)
  example: sensor.solcast_pv_forecast_peak_forecast_today
```

### Step 7: Load & Weather Configuration (Optional)

**Purpose**: Select entities for load forecasting and heat pump estimation

**Schema**:
```python
vol.Schema({
    vol.Optional("daily_load_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            device_class=SensorDeviceClass.ENERGY
        )
    ),
    vol.Optional("enable_heat_pump", default=False): bool,
    vol.Optional("outside_temperature_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            device_class=SensorDeviceClass.TEMPERATURE
        )
    ),
    vol.Optional("heat_pump_power_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            device_class=SensorDeviceClass.POWER
        )
    ),
    vol.Optional("weather_entity"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="weather"
        )
    ),
})
```

**Field Descriptions**:
```yaml
daily_load_sensor:
  name: Daily Load Sensor (Optional)
  description: Sensor tracking daily energy consumption for pattern analysis
  example: sensor.home_energy_consumption_daily
  
enable_heat_pump:
  name: Enable Heat Pump Estimation
  description: Calculate heat pump energy consumption based on temperature
  default: false
  
outside_temperature_sensor:
  name: Outside Temperature Sensor
  description: Temperature sensor for COP calculation
  example: sensor.outside_temperature
  required_if: enable_heat_pump is true
  
heat_pump_power_sensor:
  name: Heat Pump Power Sensor (Optional)
  description: Heat pump power consumption for validation
  example: sensor.heat_pump_power
  
weather_entity:
  name: Weather Forecast (Optional)
  description: Weather entity for temperature forecasting
  example: weather.home
```

### Step 8: Advanced Settings (Optional)

**Purpose**: Configure advanced optimization parameters

**Schema**:
```python
vol.Schema({
    vol.Optional("optimization_goal", default="cost_minimize"): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {"value": "cost_minimize", "label": "Minimize Cost"},
                {"value": "self_consumption", "label": "Maximize Self-Consumption"},
                {"value": "balanced", "label": "Balanced (Cost + Self-Consumption)"},
            ],
            mode=selector.SelectSelectorMode.DROPDOWN
        )
    ),
    vol.Optional("profit_threshold", default=20): vol.All(
        vol.Coerce(int),
        vol.Range(min=0, max=100)
    ),
    vol.Optional("update_interval", default=300): vol.All(
        vol.Coerce(int),
        vol.Range(min=60, max=3600)
    ),
    vol.Optional("charge_phases", default=3): vol.In([1, 2, 3]),
    vol.Optional("max_charge_current", default=50): vol.All(
        vol.Coerce(float),
        vol.Range(min=1, max=200)
    ),
})
```

**Field Descriptions**:
```yaml
optimization_goal:
  name: Optimization Goal
  description: Primary optimization objective
  options:
    - cost_minimize: Minimize electricity costs (prioritize cheap grid charging)
    - self_consumption: Maximize self-consumption (minimize grid import/export)
    - balanced: Balance between cost and self-consumption
  default: cost_minimize
  
profit_threshold:
  name: Selling Profit Threshold (%)
  description: Minimum profit margin required to sell to grid
  default: 20
  unit: "%"
  note: Only sell if current price > average price * (1 + threshold/100)
  
update_interval:
  name: Calculation Update Interval
  description: How often to recalculate optimization (seconds)
  default: 300
  unit: seconds
  
charge_phases:
  name: Grid Connection Phases
  description: Number of electrical phases available for charging
  options: [1, 2, 3]
  default: 3
  
max_charge_current:
  name: Maximum Charge Current (A)
  description: Maximum current per phase for grid charging
  default: 50
  unit: A
```

### Step 9: Summary & Confirmation

**Purpose**: Display configuration summary and create entry

**UI Elements**:
```yaml
type: summary
configuration:
  Price Configuration:
    - "Current Price: {price_sensor}"
    - "Average Price: {average_price_sensor}"
    - "Cheapest Window: {cheapest_window_sensor | 'Not configured'}"
    
  Battery Configuration:
    - "Battery SOC: {battery_soc_sensor}"
    - "Battery Power: {battery_power_sensor}"
    - "Battery Capacity: {battery_capacity_kwh} kWh"
    - "Usable Capacity: {usable_capacity_kwh} kWh"
    
  Control Configuration:
    - "Target SOC: {target_soc_entity}"
    - "Work Mode: {work_mode_entity | 'Not configured'}"
    
  PV Forecast:
    - "Enabled: {enable_pv_forecast}"
    - "Today Forecast: {pv_forecast_today | 'Not configured'}"
    
  Heat Pump:
    - "Enabled: {enable_heat_pump}"
    - "Temperature Sensor: {outside_temperature_sensor | 'Not configured'}"
    
  Advanced Settings:
    - "Optimization Goal: {optimization_goal}"
    - "Profit Threshold: {profit_threshold}%"
    - "Update Interval: {update_interval}s"

buttons:
  - label: Create
    action: create_entry
  - label: Back
    action: previous_step
```

## Config Entry Data Structure

**Stored in `config_entry.data`**:
```python
{
    # Price entities
    "price_sensor": "sensor.rce_pse_price",
    "average_price_sensor": "sensor.rce_pse_today_average_price",
    "cheapest_window_sensor": "binary_sensor.rce_pse_today_cheapest_window_active",
    "expensive_window_sensor": "binary_sensor.rce_pse_today_expensive_window_active",
    "tomorrow_price_sensor": "sensor.rce_pse_tomorrow_price",
    
    # Battery entities
    "battery_soc_sensor": "sensor.deye_hybrid_battery_soc",
    "battery_power_sensor": "sensor.deye_hybrid_battery_power",
    "battery_voltage_sensor": "sensor.deye_hybrid_battery_voltage",
    "battery_current_sensor": "sensor.deye_hybrid_battery_current",
    
    # Battery parameters
    "battery_capacity_ah": 200.0,
    "battery_voltage": 48.0,
    "battery_efficiency": 95.0,
    "min_soc": 10,
    "max_soc": 100,
    
    # Control entities
    "target_soc_entity": "number.deye_hybrid_max_soc",
    "work_mode_entity": "select.deye_hybrid_work_mode",
    "charge_current_entity": "number.deye_hybrid_battery_charge_current",
    "discharge_current_entity": "number.deye_hybrid_battery_discharge_current",
    "grid_charge_switch": "switch.deye_hybrid_grid_charge",
    
    # PV forecast (optional)
    "enable_pv_forecast": True,
    "pv_forecast_today": "sensor.solcast_pv_forecast_forecast_today",
    "pv_forecast_tomorrow": "sensor.solcast_pv_forecast_forecast_tomorrow",
    "pv_forecast_remaining": "sensor.solcast_pv_forecast_forecast_remaining_today",
    "pv_peak_forecast": "sensor.solcast_pv_forecast_peak_forecast_today",
    
    # Load & weather (optional)
    "daily_load_sensor": "sensor.home_energy_consumption_daily",
    "enable_heat_pump": True,
    "outside_temperature_sensor": "sensor.outside_temperature",
    "heat_pump_power_sensor": "sensor.heat_pump_power",
    "weather_entity": "weather.home",
    
    # Advanced settings
    "optimization_goal": "cost_minimize",
    "profit_threshold": 20,
    "update_interval": 300,
    "charge_phases": 3,
    "max_charge_current": 50.0,
}
```

## Options Flow (Reconfiguration)

**Allow users to update configuration after initial setup**:

```python
class EnergyOptimizerOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Energy Optimizer."""
    
    async def async_step_init(self, user_input=None):
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        
        # Pre-fill with current config
        current_config = self.config_entry.data
        
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                # Allow changing battery parameters
                vol.Required(
                    "battery_capacity_ah",
                    default=current_config.get("battery_capacity_ah", 200)
                ): vol.All(vol.Coerce(float), vol.Range(min=1, max=1000)),
                # ... other configurable options
            })
        )
```

## Implementation Example: Reading Configured Entities

**In sensor platform**:
```python
class EnergyOptimizerBatteryReserveSensor(SensorEntity):
    """Battery reserve sensor."""
    
    async def async_update(self):
        """Update sensor state."""
        # Read configured entity IDs from config entry
        battery_soc_entity = self.config_entry.data["battery_soc_sensor"]
        
        # Get current state
        soc_state = self.hass.states.get(battery_soc_entity)
        if not soc_state or soc_state.state == STATE_UNAVAILABLE:
            self._attr_available = False
            return
        
        current_soc = float(soc_state.state)
        min_soc = self.config_entry.data["min_soc"]
        capacity_ah = self.config_entry.data["battery_capacity_ah"]
        voltage = self.config_entry.data["battery_voltage"]
        
        # Calculate reserve
        reserve_kwh = (current_soc - min_soc) / 100 * capacity_ah * voltage / 1000
        self._attr_native_value = round(reserve_kwh, 2)
```

**In service implementation**:
```python
async def async_calculate_charge_soc(hass: HomeAssistant, config_entry, call):
    """Calculate optimal charge SOC service."""
    # Read price data from configured entities
    price_sensor = config_entry.data["price_sensor"]
    avg_price_sensor = config_entry.data["average_price_sensor"]
    
    current_price = float(hass.states.get(price_sensor).state)
    average_price = float(hass.states.get(avg_price_sensor).state)
    
    # Read battery state
    battery_soc_sensor = config_entry.data["battery_soc_sensor"]
    current_soc = float(hass.states.get(battery_soc_sensor).state)
    
    # Calculate optimal target SOC
    target_soc = calculate_optimal_soc(
        current_price, average_price, current_soc, config_entry.data
    )
    
    # Write to control entity
    target_soc_entity = config_entry.data["target_soc_entity"]
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": target_soc_entity, "value": target_soc},
        blocking=True
    )
    
    return {
        "target_soc": target_soc,
        "current_soc": current_soc,
        "current_price": current_price,
        "average_price": average_price,
    }
```

## Error Handling

### Entity Not Found
```python
if not hass.states.get(entity_id):
    raise ServiceValidationError(
        f"Entity {entity_id} not found. Please reconfigure Energy Optimizer."
    )
```

### Entity State Unavailable
```python
state = hass.states.get(entity_id)
if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
    _LOGGER.warning("Entity %s is unavailable, skipping calculation", entity_id)
    return None  # Graceful degradation
```

### Invalid Entity Type
```python
if hass.states.get(entity_id).domain != expected_domain:
    raise ServiceValidationError(
        f"Entity {entity_id} must be a {expected_domain} entity"
    )
```

### Write Permission Denied
```python
try:
    await hass.services.async_call(domain, service, data, blocking=True)
except Exception as err:
    raise ServiceValidationError(
        f"Failed to write to {data['entity_id']}: {err}"
    )
```

## Summary

This entity-based configuration approach provides:

✅ **Flexibility**: Compatible with any integration exposing similar entities  
✅ **User Control**: Users select exactly which entities to use  
✅ **No Hard Dependencies**: Works without requiring specific integrations  
✅ **Clear Guidance**: Recommendations point to proven integrations  
✅ **Runtime Safety**: Validation checks entity availability and type  
✅ **Graceful Degradation**: Handles unavailable entities without crashing  

Energy Optimizer focuses on **coordination and calculation**, reading from and writing to user-configured entities without knowledge of underlying hardware or APIs.
