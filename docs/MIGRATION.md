# Migration Guide: YAML to Energy Optimizer Integration

This guide helps you migrate from YAML-based energy optimization automations to the Energy Optimizer custom integration.

## Why Migrate?

### Benefits of Integration Approach

- **Simplified Configuration**: Entity-based config flow instead of complex YAML
- **Better Performance**: Native Python calculations instead of Jinja templates
- **Maintainability**: Centralized logic, easier to update and debug
- **Extensibility**: Services and sensors for automation flexibility
- **Type Safety**: Validated inputs, proper error handling
- **HACS Support**: Easy installation and updates

## Pre-Migration Checklist

### 1. Backup Current Configuration

```bash
# Backup your configuration files
cp automations.yaml automations.yaml.backup
cp sensors.yaml sensors.yaml.backup
cp templates.yaml templates.yaml.backup
cp -r custom_templates/ custom_templates.backup/
```

### 2. Install Required Integrations

Ensure these integrations are installed:

- **ha-rce-pse**: For price data and windows
- **ha-solarman**: For battery/inverter control
- **Solcast Solar** (optional): For PV forecasts

### 3. Document Current Entity Names

List your current entity IDs:

```yaml
# Price entities
- sensor.rce_pse_price
- sensor.rce_pse_today_average_price
- binary_sensor.rce_pse_today_cheapest_window_active
- binary_sensor.rce_pse_today_expensive_window_active

# Battery entities
- sensor.deye_hybrid_battery_soc
- sensor.deye_hybrid_battery_power
- number.deye_hybrid_max_soc

# PV entities (if using)
- sensor.solcast_pv_forecast_forecast_today
- sensor.solcast_pv_forecast_forecast_tomorrow
```

## Migration Steps

### Step 1: Install Energy Optimizer

1. Open HACS → Integrations
2. Search for "Energy Optimizer"
3. Click "Download"
4. Restart Home Assistant

### Step 2: Configure Integration

1. Go to Settings → Devices & Services
2. Click "+ Add Integration"
3. Search for "Energy Optimizer"
4. Complete the configuration wizard with your entity IDs

### Step 3: Verify Sensors

After configuration, verify new sensors are created:

```yaml
# Old template sensors → New integration sensors
sensor.battery_reserve_kwh → sensor.energy_optimizer_battery_reserve
sensor.battery_space_kwh → sensor.energy_optimizer_battery_space
sensor.required_energy_morning → sensor.energy_optimizer_required_energy_morning
```

### Step 4: Migrate Automations

#### Old YAML Automation (Automation 10 - Morning Grid Buy)

```yaml
alias: "10 Morning Grid Buy"
trigger:
  - platform: state
    entity_id: binary_sensor.rce_pse_today_cheapest_window_active
    to: "on"
condition:
  - condition: numeric_state
    entity_id: sensor.deye_hybrid_battery_soc
    below: 80
action:
  - service: script.calculate_charge_target
  - service: number.set_value
    target:
      entity_id: number.deye_hybrid_max_soc
    data:
      value: "{{ states('input_number.calculated_target_soc') }}"
```

#### New Integration-Based Automation

```yaml
alias: "Morning Grid Buy (Energy Optimizer)"
trigger:
  - platform: state
    entity_id: binary_sensor.rce_pse_today_cheapest_window_active
    to: "on"
condition:
  - condition: numeric_state
    entity_id: sensor.deye_hybrid_battery_soc
    below: 80
action:
  - service: energy_optimizer.calculate_charge_soc
    data:
      hours: 12
      force_charge: true
```

#### Old YAML Automation (Automation 60 - Evening Grid Sell)

```yaml
alias: "60 Evening Grid Sell"
trigger:
  - platform: state
    entity_id: binary_sensor.rce_pse_today_expensive_window_active
    to: "on"
condition:
  - condition: template
    value_template: "{{ states('sensor.battery_reserve_kwh')|float > 5 }}"
  - condition: template
    value_template: >
      {{ states('sensor.rce_pse_price')|float > 
         states('sensor.rce_pse_today_average_price')|float * 1.2 }}
action:
  - service: select.select_option
    target:
      entity_id: select.deye_hybrid_work_mode
    data:
      option: "Selling First"
```

#### New Integration-Based Automation

```yaml
alias: "Evening Grid Sell (Energy Optimizer)"
trigger:
  - platform: state
    entity_id: binary_sensor.rce_pse_today_expensive_window_active
    to: "on"
condition:
  - condition: numeric_state
    entity_id: sensor.energy_optimizer_surplus_energy
    above: 5
action:
  - service: energy_optimizer.calculate_sell_energy
    data:
      min_profit_margin: 20
      auto_set_work_mode: true
```

## Entity Mapping Table

### Template Sensors → Integration Sensors

| Old Template Sensor | New Integration Sensor | Notes |
|---------------------|------------------------|-------|
| `sensor.battery_reserve_kwh` | `sensor.energy_optimizer_battery_reserve` | Direct replacement |
| `sensor.battery_space_kwh` | `sensor.energy_optimizer_battery_space` | Direct replacement |
| `sensor.battery_capacity_kwh` | `sensor.energy_optimizer_battery_capacity` | Direct replacement |
| `sensor.required_energy_morning` | `sensor.energy_optimizer_required_energy_morning` | Now calculated from history |
| `sensor.required_energy_afternoon` | `sensor.energy_optimizer_required_energy_afternoon` | Improved calculation |
| `sensor.required_energy_evening` | `sensor.energy_optimizer_required_energy_evening` | Improved calculation |
| `sensor.heat_pump_estimation` | `sensor.energy_optimizer_heat_pump_estimation` | Enhanced COP curve |

### Scripts → Services

| Old Script | New Service | Notes |
|------------|-------------|-------|
| `script.calculate_charge_target` | `energy_optimizer.calculate_charge_soc` | More parameters available |
| `script.calculate_sell_energy` | `energy_optimizer.calculate_sell_energy` | Built-in profitability check |
| `script.estimate_heat_pump` | `energy_optimizer.estimate_heat_pump_usage` | Temperature-based COP |
| N/A | `energy_optimizer.overnight_schedule` | New comprehensive scheduler |

## Advanced Migration

### Custom Jinja Macros → Python Functions

If you customized Jinja macros, you can extend the integration's calculation library.

#### Example: Custom Battery Reserve Calculation

**Old Jinja Macro** (`custom_templates/calculations.jinja`):
```jinja
{% macro battery_reserve_with_cushion(soc, min_soc, capacity_ah, voltage, cushion_kwh) %}
  {{ ((soc - min_soc) / 100 * capacity_ah * voltage / 1000 - cushion_kwh) | max(0) }}
{% endmacro %}
```

**New Python Function** (extend `calculations/battery.py`):
```python
def calculate_battery_reserve_with_cushion(
    current_soc: float,
    min_soc: float,
    capacity_ah: float,
    voltage: float,
    cushion_kwh: float
) -> float:
    """Calculate battery reserve with safety cushion."""
    base_reserve = calculate_battery_reserve(current_soc, min_soc, capacity_ah, voltage)
    return max(0.0, base_reserve - cushion_kwh)
```

### Multi-Phase Charging Current

The integration already implements multi-phase charging logic. If your YAML had custom phase definitions:

```python
# custom_components/energy_optimizer/calculations/charging.py
# Modify phases in get_expected_current_multi_phase()

phases = [
    (0, 70, 23),   # Phase 1: Customize currents here
    (70, 90, 9),   # Phase 2
    (90, 100, 4),  # Phase 3
]
```

## Cleanup After Migration

### 1. Disable Old Automations

Don't delete immediately - disable for monitoring period:

```yaml
# In automations.yaml, add mode: disabled
- id: "10_morning_grid_buy"
  alias: "10 Morning Grid Buy"
  mode: single
  # Add this:
  # disabled: true
```

### 2. Remove Old Template Sensors (After Testing)

```yaml
# Comment out or remove from sensors.yaml/templates.yaml
# - platform: template
#   sensors:
#     battery_reserve_kwh:
#       ...
```

### 3. Archive Custom Templates

```bash
# Move to archive folder
mkdir -p custom_templates/archive
mv custom_templates/*.jinja custom_templates/archive/
```

### 4. Clean Up Scripts

```yaml
# Remove obsolete scripts from scripts.yaml
# script:
#   calculate_charge_target:
#     ...
```

## Testing & Validation

### 1. Compare Sensor Values

Run side-by-side for a day:

```yaml
# Create comparison automation
automation:
  - alias: "Compare Battery Reserve Values"
    trigger:
      - platform: time_pattern
        minutes: "/5"
    action:
      - service: notify.persistent_notification
        data:
          message: >
            Old: {{ states('sensor.battery_reserve_kwh') }}
            New: {{ states('sensor.energy_optimizer_battery_reserve') }}
```

### 2. Monitor Service Calls

Check that services execute correctly:

```yaml
# Settings → System → Logs
# Filter for: energy_optimizer
```

### 3. Verify Automation Triggers

Ensure new automations trigger at expected times.

## Troubleshooting

### Sensors Not Updating

**Problem**: Integration sensors show "unavailable"

**Solution**:
- Check source entities are available
- Verify entity IDs in config match your system
- Review Home Assistant logs for errors

### Different Calculation Results

**Problem**: New sensors show different values than templates

**Solution**:
- Python uses 64-bit floats (more precision)
- Check battery parameter configuration
- Verify efficiency and margin values

### Services Not Working

**Problem**: Service calls fail or do nothing

**Solution**:
- Ensure target SOC entity is writable
- Check service parameters are valid
- Review service call in Developer Tools → Services

### Missing Features

**Problem**: Integration doesn't support custom logic

**Solution**:
- Use template sensors to extend integration sensors
- Create custom automations combining services
- Submit feature request on GitHub

## Rollback Plan

If migration issues occur:

1. **Re-enable YAML automations**:
   ```yaml
   # Remove disabled: true from automations.yaml
   ```

2. **Restore template sensors**:
   ```bash
   cp sensors.yaml.backup sensors.yaml
   ```

3. **Remove integration**:
   - Settings → Integrations → Energy Optimizer → Delete

4. **Restart Home Assistant**

## Support

- **GitHub Issues**: https://github.com/plebann/EnergyOptimizer/issues
- **Documentation**: https://github.com/plebann/EnergyOptimizer/wiki
- **Community**: https://community.home-assistant.io/

## Example: Complete Migration

### Before (YAML Configuration)

```yaml
# automations.yaml (12 automations, ~400 lines)
# sensors.yaml (8 template sensors, ~200 lines)
# templates.yaml (6 macros, ~150 lines)
# python_scripts/ (2 scripts, ~100 lines)
# Total: ~850 lines of configuration
```

### After (Integration)

```yaml
# Configuration via UI (no YAML)
# Automations: 2-3 simple automations using services
# Total: ~50 lines of automation YAML
```

**Maintenance improvement**: 94% reduction in configuration code!

---

**Ready to migrate?** Follow the steps above and enjoy simplified energy optimization! 🚀
