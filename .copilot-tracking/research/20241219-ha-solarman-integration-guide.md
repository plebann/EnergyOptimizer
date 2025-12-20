<!-- markdownlint-disable-file -->
# ha-solarman Integration Guide for Energy Optimizer

## Overview

This document provides guidance on integrating **ha-solarman** (domain: `solarman`) with the Energy Optimizer HACS integration. The ha-solarman integration provides Modbus communication with Solarman-compatible inverters, exposing control entities and sensors for battery management.

**Repository**: https://github.com/davidrapan/ha-solarman
**Version Analyzed**: v25.08.16
**Supported Inverters**: Deye, Solis, Solax, Sofar, Afore, ZCS, Microtek, and other Solarman-compatible devices
**Communication**: Modbus over TCP (Solarman logger, ESP, Waveshare, Ethernet logger)

## Prerequisites

### Installing ha-solarman

1. **Add to HACS**:
   - Go to HACS → Integrations
   - Click "+" button
   - Search for "Solarman"
   - Install ha-solarman by David Rapan

2. **Configure Integration**:
   - Go to Settings → Devices & Services
   - Click "+ ADD INTEGRATION"
   - Search for "Solarman"
   - Configure:
     - **Host**: IP address of Solarman logger/inverter
     - **Port**: 8899 (default)
     - **Serial Number**: Inverter serial number
     - **Lookup File**: Select inverter model or "Auto" for detection
     - **Options**:
       - MPPT: Number of MPPT trackers (1-12)
       - Phase: Number of phases (1-3)
       - Pack: Battery pack number (-1 for auto)
       - Battery Nominal Voltage: 48V (default)
       - Battery Life Cycle Rating: 6000 cycles (default)

3. **Verify Installation**:
   - Check that inverter device appears in Devices & Services
   - Verify entities are created (sensors, numbers, selects)
   - Test writing to a number entity (e.g., target SOC)

## Entity Types Provided by ha-solarman

### 1. Number Entities (Writable Controls)

Number entities in ha-solarman are writable controls based on inverter definition files. Common entities for battery management:

| Entity Pattern | Purpose | Unit | Range | Notes |
|---------------|---------|------|-------|-------|
| `number.{inverter}_battery_capacity` | Battery capacity setting | Ah | Varies | Configuration parameter |
| `number.{inverter}_battery_charge_current` | Max charging current | A | Varies | Limit charging rate |
| `number.{inverter}_battery_discharge_current` | Max discharging current | A | Varies | Limit discharge rate |
| `number.{inverter}_battery_charge_voltage` | Target charge voltage | V | Varies | Advanced setting |
| `number.{inverter}_grid_charge_current_limit` | Grid charging current limit | A | Varies | Control grid charging |
| `number.{inverter}_max_soc` | Maximum SOC target | % | 0-100 | Upper SOC limit |
| `number.{inverter}_battery_low_soc` | Low SOC protection | % | 0-100 | Minimum SOC threshold |

**Implementation Details**:
- Entities are defined in YAML definition files per inverter model
- Support scale factors and offsets for unit conversion
- Use Modbus WRITE_MULTIPLE_REGISTERS function code
- Can have configurable min/max/step values

**Example from code**:
```python
class SolarmanNumberEntity(SolarmanWritableEntity, NumberEntity):
    async def async_set_native_value(self, value: float) -> None:
        """Update the setting."""
        value_int = int(value if self.scale is None else value / self.scale)
        if self.offset is not None:
            value_int += self.offset
        await self.write(value_int if value_int < 0xFFFF else 0xFFFF, get_number(value))
```

### 2. Select Entities (Mode Controls)

Select entities provide dropdown selection for inverter operating modes:

| Entity Pattern | Purpose | Options | Notes |
|---------------|---------|---------|-------|
| `select.{inverter}_work_mode` | Inverter work mode | Selling First, Battery First, Zero Export, etc. | Primary operating mode |
| `select.{inverter}_charge_mode` | Battery charge priority | Priority/Timed | Charging behavior |
| `select.{inverter}_ac_charge_enable` | AC/Grid charging | Enabled, Disabled | Allow grid charging |

**Common Work Modes** (varies by inverter model):
- **Selling First**: Export surplus to grid
- **Battery First**: Prioritize battery charging
- **Zero Export**: No grid export
- **Load First**: Prioritize local loads
- **Smart**: Automatic optimization (if available)

**Implementation Details**:
- Uses lookup dictionaries to map display values to Modbus register values
- Supports bit-based selections for multiple flags
- Can have mask values for partial register updates

**Example from code**:
```python
class SolarmanSelectEntity(SolarmanWritableEntity, SelectEntity):
    async def async_select_option(self, option: str):
        """Change the selected option."""
        await self.write(self.get_key(option), option)
```

### 3. Sensor Entities (Read-Only Monitoring)

Sensor entities provide real-time monitoring data:

| Entity Pattern | Purpose | Unit | State Class | Device Class |
|---------------|---------|------|-------------|--------------|
| `sensor.{inverter}_battery_soc` | Battery state of charge | % | measurement | battery |
| `sensor.{inverter}_battery_power` | Battery power (+ discharge, - charge) | W | measurement | power |
| `sensor.{inverter}_battery_voltage` | Battery voltage | V | measurement | voltage |
| `sensor.{inverter}_battery_current` | Battery current | A | measurement | current |
| `sensor.{inverter}_battery_temperature` | Battery temperature | °C | measurement | temperature |
| `sensor.{inverter}_grid_power` | Grid power (+ import, - export) | W | measurement | power |
| `sensor.{inverter}_load_power` | Load consumption | W | measurement | power |
| `sensor.{inverter}_pv_power` | PV production | W | measurement | power |
| `sensor.{inverter}_today_battery_charge` | Daily battery charge | kWh | total_increasing | energy |
| `sensor.{inverter}_today_battery_discharge` | Daily battery discharge | kWh | total_increasing | energy |
| `sensor.{inverter}_total_battery_charge` | Total battery charge | kWh | total_increasing | energy |
| `sensor.{inverter}_total_battery_discharge` | Total battery discharge | kWh | total_increasing | energy |

**Special Calculated Sensors**:
- `sensor.{inverter}_battery_capacity`: Auto-calculated from charge/discharge cycles
- `sensor.{inverter}_battery_soh`: Battery state of health (based on cycle count)
- `sensor.{inverter}_battery_state`: "charging", "discharging", or "idle"
- `sensor.{inverter}_today_battery_life_cycles`: Daily cycle count
- `sensor.{inverter}_total_battery_life_cycles`: Total cycle count

**Battery State Logic** (from code):
```python
battery_power = get_tuple(self.coordinator.data.get("battery_power_sensor"))
if battery_power:
    self.set_state("discharging" if battery_power > 50 else "charging" if battery_power < -50 else "idle")
```

### 4. Switch Entities (On/Off Controls)

Switch entities for binary controls:

| Entity Pattern | Purpose | Default State | Notes |
|---------------|---------|---------------|-------|
| `switch.{inverter}_grid_charge` | Enable grid charging | OFF | Allow charging from grid |
| `switch.{inverter}_battery_charge` | Enable battery charging | ON | Master charge enable |
| `switch.{inverter}_battery_discharge` | Enable battery discharge | ON | Master discharge enable |

**Implementation Details**:
- Supports bit-level operations for register flags
- Can have custom on/off values (not always 1/0)

## Entity Naming Convention

ha-solarman uses a consistent naming scheme:
- **Device Name**: User-configurable (default: "Inverter")
- **Entity ID Format**: `{platform}.{device_name}_{entity_name}`
- **Friendly Name**: From YAML definition files

**Example**:
- Device Name: `deye_hybrid`
- Entity ID: `number.deye_hybrid_max_soc`
- Friendly Name: "Max SOC"

## Energy Optimizer Integration Strategy

### Config Flow Entity Selection

In Energy Optimizer config flow, users should select ha-solarman entities:

```python
STEP_BATTERY_SCHEMA = vol.Schema({
    vol.Required("battery_soc_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class="battery")
    ),
    vol.Required("battery_power_sensor"): selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class="power")
    ),
    vol.Required("battery_capacity_number"): selector.EntitySelector(
        selector.EntitySelectorConfig(domain="number")
    ),
    vol.Optional("battery_soc_target_number"): selector.EntitySelector(
        selector.EntitySelectorConfig(domain="number")
    ),
    vol.Optional("inverter_work_mode_select"): selector.EntitySelector(
        selector.EntitySelectorConfig(domain="select")
    ),
})
```

### Automation Service Example

Energy Optimizer service that controls ha-solarman entities:

```python
async def async_calculate_and_set_charge_soc(self, call):
    """Calculate optimal SOC and update inverter."""
    # Get ha-rce-pse price data
    price_sensor = self.hass.states.get("sensor.rce_pse_price")
    cheapest_window_start = self.hass.states.get("sensor.rce_pse_today_cheapest_window_start").state
    
    # Get ha-solarman battery data
    battery_soc = float(self.hass.states.get("sensor.deye_hybrid_battery_soc").state)
    battery_capacity = float(self.hass.states.get("number.deye_hybrid_battery_capacity").state)
    
    # Calculate optimal SOC (Energy Optimizer calculation logic)
    target_soc = await self._calculate_optimal_soc(
        current_soc=battery_soc,
        capacity=battery_capacity,
        price_data=price_sensor.attributes.get("prices"),
        cheapest_window=cheapest_window_start
    )
    
    # Write to ha-solarman number entity
    await self.hass.services.async_call(
        "number",
        "set_value",
        {
            "entity_id": "number.deye_hybrid_max_soc",
            "value": target_soc
        }
    )
    
    return {
        "target_soc": target_soc,
        "current_soc": battery_soc,
        "cheapest_window_start": cheapest_window_start
    }
```

### Blueprint Example

Automation blueprint using Energy Optimizer + ha-solarman:

```yaml
blueprint:
  name: Energy Optimizer - Charge During Cheapest Window
  description: Automatically set battery target SOC during cheapest price window
  domain: automation
  input:
    cheapest_window_binary:
      name: Cheapest Window Binary Sensor
      selector:
        entity:
          domain: binary_sensor
          integration: rce_pse
    battery_soc_sensor:
      name: Battery SOC Sensor
      selector:
        entity:
          domain: sensor
          integration: solarman
          device_class: battery
    target_soc_number:
      name: Target SOC Number
      selector:
        entity:
          domain: number
          integration: solarman

trigger:
  - platform: state
    entity_id: !input cheapest_window_binary
    to: "on"

condition:
  - condition: numeric_state
    entity_id: !input battery_soc_sensor
    below: 80

action:
  - service: energy_optimizer.calculate_charge_soc
    data:
      battery_soc_sensor: !input battery_soc_sensor
      target_soc_number: !input target_soc_number
```

## Inverter Definition Files

ha-solarman uses YAML definition files to describe inverter entities. These are located in `custom_components/solarman/inverter_definitions/`.

**Common Definition Files**:
- `deye_hybrid.yaml` - Deye hybrid inverters (SUN-xK-SG01/03/04/05LP1/3)
- `deye_sg04lp3.yaml` - Deye SG04LP3 specific
- `deye_string.yaml` - Deye string inverters
- `solis_hybrid.yaml` - Solis hybrid inverters
- `sofar_lsw3.yaml` - Sofar LSW-3 series

**Definition Structure** (simplified):
```yaml
default:
  update_interval: 60
  code: 0x03  # READ_HOLDING_REGISTERS

parameters:
  - group: Battery
    items:
      - name: Battery SOC
        class: battery
        state_class: measurement
        uom: "%"
        scale: 1
        rule: 1
        registers: [0x0184]
        icon: mdi:battery
        
      - name: Max SOC
        class: ""
        platform: number
        uom: "%"
        scale: 1
        rule: 1
        registers: [0x0248]
        write:
          registers: [0x0248]
          code: 0x10  # WRITE_MULTIPLE_REGISTERS
        range:
          min: 10
          max: 100
        icon: mdi:battery-arrow-up
```

**Key Fields**:
- `registers`: Modbus register addresses (hex)
- `scale`: Scaling factor for values
- `rule`: Validation rule (1=direct, 2=signed, 3=scale, 4=bitmask, 5=version)
- `platform`: Entity platform (sensor, number, select, switch, button)
- `write`: Write configuration for writable entities
- `lookup`: Value mapping for select entities

## Testing Strategy

### Manual Testing Checklist

- [ ] ha-solarman integration installed and configured
- [ ] Inverter device visible in Devices & Services
- [ ] Battery SOC sensor updating (check state and last_updated)
- [ ] Battery power sensor showing correct values (negative when charging)
- [ ] Number entities writable (test setting Max SOC)
- [ ] Select entities functional (test changing work mode)
- [ ] Energy Optimizer can read ha-solarman sensor states
- [ ] Energy Optimizer can write to ha-solarman number entities
- [ ] Services properly update inverter settings via ha-solarman

### Integration Testing

```python
async def test_solarman_entity_write(hass):
    """Test writing to ha-solarman number entity."""
    # Mock ha-solarman number entity
    hass.states.async_set(
        "number.test_inverter_max_soc",
        "80",
        attributes={"min": 10, "max": 100, "step": 1}
    )
    
    # Call Energy Optimizer service
    await hass.services.async_call(
        "energy_optimizer",
        "calculate_charge_soc",
        {"battery_capacity": 200},
        blocking=True
    )
    
    # Verify ha-solarman entity was updated
    state = hass.states.get("number.test_inverter_max_soc")
    assert float(state.state) == 95  # Expected calculated value
```

## Common Entity Mappings

### Old YAML Automation → ha-solarman Entities

| Old Entity/Config | ha-solarman Entity | Notes |
|------------------|-------------------|-------|
| `number.inverter_max_soc` | `number.{inverter}_max_soc` | Direct mapping |
| `select.inverter_work_mode` | `select.{inverter}_work_mode` | Check available options |
| `sensor.battery_soc` | `sensor.{inverter}_battery_soc` | Read-only monitoring |
| `sensor.battery_power` | `sensor.{inverter}_battery_power` | Negative = charging |
| Grid charge current setting | `number.{inverter}_grid_charge_current_limit` | May need to enable first |
| Battery charge enable | `switch.{inverter}_grid_charge` | Binary on/off |

### Entity Discovery in Config Flow

Energy Optimizer should auto-discover ha-solarman entities:

```python
async def async_step_inverter(self, user_input=None):
    """Select inverter entities from ha-solarman."""
    errors = {}
    
    if user_input is not None:
        return self.async_create_entry(title="Energy Optimizer", data=user_input)
    
    # Find all solarman entities
    entity_registry = er.async_get(self.hass)
    solarman_entities = {
        entry.entity_id: entry
        for entry in entity_registry.entities.values()
        if entry.platform == "solarman"
    }
    
    # Filter by entity type
    battery_soc_sensors = [
        entity_id for entity_id, entry in solarman_entities.items()
        if entity_id.startswith("sensor.") and "battery_soc" in entity_id
    ]
    
    max_soc_numbers = [
        entity_id for entity_id, entry in solarman_entities.items()
        if entity_id.startswith("number.") and "max_soc" in entity_id
    ]
    
    return self.async_show_form(
        step_id="inverter",
        data_schema=vol.Schema({
            vol.Required("battery_soc_sensor", default=battery_soc_sensors[0] if battery_soc_sensors else None): vol.In(battery_soc_sensors),
            vol.Optional("max_soc_number", default=max_soc_numbers[0] if max_soc_numbers else None): vol.In(max_soc_numbers),
        }),
        errors=errors
    )
```

## Advanced: Custom Sensor Creation

Energy Optimizer can create template sensors based on ha-solarman data:

```python
class EnergyOptimizerBatteryReserveSensor(SensorEntity):
    """Calculate battery reserve based on ha-solarman SOC."""
    
    def __init__(self, hass, config):
        self._hass = hass
        self._battery_soc_entity = config["battery_soc_sensor"]
        self._battery_capacity_entity = config["battery_capacity_number"]
        self._min_soc = config.get("min_soc", 10)
    
    @property
    def native_value(self):
        """Calculate reserve kWh."""
        soc_state = self._hass.states.get(self._battery_soc_entity)
        capacity_state = self._hass.states.get(self._battery_capacity_entity)
        
        if not soc_state or not capacity_state:
            return None
        
        current_soc = float(soc_state.state)
        capacity_ah = float(capacity_state.state)
        battery_voltage = 48  # Or read from config/entity
        
        # Calculate reserve above minimum SOC
        reserve_soc = current_soc - self._min_soc
        reserve_kwh = (reserve_soc / 100) * (capacity_ah * battery_voltage / 1000)
        
        return round(reserve_kwh, 2)
    
    @property
    def unit_of_measurement(self):
        return "kWh"
    
    @property
    def device_class(self):
        return "energy"
```

## Troubleshooting

### Issue: ha-solarman entities not found

**Cause**: Integration not installed or inverter not configured

**Solution**:
1. Install ha-solarman from HACS
2. Configure integration with inverter IP and serial number
3. Wait for initial data fetch (60 seconds default)
4. Verify entities in Developer Tools → States

### Issue: Number entity write fails

**Cause**: Register write protection or invalid value range

**Solution**:
1. Check entity attributes for min/max/step values
2. Verify inverter work mode allows parameter changes
3. Check ha-solarman logs for Modbus errors
4. Ensure value is within inverter's acceptable range

### Issue: Sensor values show "unavailable"

**Cause**: Communication error with inverter

**Solution**:
1. Check network connectivity to Solarman logger
2. Verify correct IP address and port (8899)
3. Check ha-solarman integration logs
4. Restart ha-solarman integration
5. Verify inverter is powered on and responsive

### Issue: Entity names don't match documentation

**Cause**: Different inverter model or definition file

**Solution**:
1. Check which definition file is being used (integration config)
2. Look at actual entity IDs in Developer Tools
3. Use entity selector in Energy Optimizer config flow
4. Don't hardcode entity IDs - let users select them

## Documentation Requirements

### README.md

```markdown
## Prerequisites

Before installing Energy Optimizer, you must install:

1. **ha-rce-pse** (REQUIRED)
   - Repository: https://github.com/Lewa-Reka/ha-rce-pse
   - Install via HACS
   - Provides all RCE price data and price window calculations

2. **ha-solarman** (REQUIRED)
   - Repository: https://github.com/davidrapan/ha-solarman
   - Install via HACS
   - Provides inverter and battery control entities
   - Configure with your Solarman logger IP and inverter serial number

3. **Solcast Solar** (OPTIONAL)
   - For PV production forecasting
   - Install via HACS
```

### CONFIGURATION.md

```markdown
## Inverter Entity Selection

During setup, you'll select entities from your ha-solarman integration:

1. **Battery SOC Sensor** (REQUIRED)
   - Typically: `sensor.{inverter}_battery_soc`
   - Used to monitor current battery state

2. **Battery Power Sensor** (REQUIRED)
   - Typically: `sensor.{inverter}_battery_power`
   - Negative values indicate charging

3. **Battery Capacity** (REQUIRED)
   - Typically: `number.{inverter}_battery_capacity`
   - Or manually enter capacity in Ah

4. **Target SOC Control** (OPTIONAL)
   - Typically: `number.{inverter}_max_soc`
   - Allows Energy Optimizer to adjust charge target

5. **Work Mode Control** (OPTIONAL)
   - Typically: `select.{inverter}_work_mode`
   - Allows mode switching (Battery First, Selling First, etc.)
```

## Summary

### ha-solarman Provides

✓ **Inverter Communication** - Modbus protocol over TCP
✓ **Battery Monitoring** - SOC, power, voltage, current, temperature sensors
✓ **Battery Control** - Target SOC, charge/discharge current limits
✓ **Work Mode Control** - Operating mode selection (Battery First, Selling First, etc.)
✓ **Grid Charge Control** - Enable/disable grid charging
✓ **Multi-Brand Support** - Deye, Solis, Solax, Sofar, and others via definition files
✓ **Auto-Detection** - Automatic inverter model detection (when supported)

### Energy Optimizer Should

- **Reference** ha-solarman entities in config flow (entity selectors)
- **Read** battery state from ha-solarman sensors
- **Write** calculated targets to ha-solarman number entities
- **Coordinate** work mode changes via ha-solarman select entities
- **Calculate** optimal settings based on ha-rce-pse price data + ha-solarman battery data
- **Provide** services that combine multiple data sources for intelligent decisions

### Architecture Integration

```
┌─────────────────────────┐
│   ha-rce-pse            │ ← Price & Window Data
│   - Current prices      │
│   - Statistics          │
│   - Price windows       │
│   - Binary sensors      │
└──────────┬──────────────┘
           │
           ↓ consumes
┌─────────────────────────┐
│   energy_optimizer      │ ← Calculation Engine
│   - Battery calcs       │
│   - Heat pump estimate  │
│   - Optimization logic  │
│   - Services            │
└──────────┬──────────────┘
           │
           ↓ controls
┌─────────────────────────┐
│   ha-solarman           │ ← Inverter Control
│   - Battery sensors     │
│   - Number entities     │
│   - Select entities     │
│   - Modbus comms        │
└─────────────────────────┘
           │
           ↓ Modbus TCP
┌─────────────────────────┐
│   Solarman Logger       │ ← Hardware
│   + Inverter Device     │
└─────────────────────────┘
```

This architecture ensures:
- **Separation**: Each integration has clear responsibility
- **Flexibility**: Users can use alternative integrations if needed
- **Maintainability**: Updates to protocols handled by respective integrations
- **Reliability**: Proven integrations for hardware communication
