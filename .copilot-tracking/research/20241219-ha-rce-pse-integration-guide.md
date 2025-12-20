<!-- markdownlint-disable-file -->
# ha-rce-pse Integration Guide for Energy Optimizer

## Overview

This document provides guidance on integrating **ha-rce-pse** (domain: `rce_pse`) with the Energy Optimizer HACS integration. The ha-rce-pse integration provides all RCE price data and price window calculations, eliminating the need to implement these features in Energy Optimizer.

**Repository**: https://github.com/Lewa-Reka/ha-rce-pse
**Version Analyzed**: v1.3.2
**Update Interval**: 30 minutes
**Tomorrow Data Available**: After 14:00 CET

## Prerequisites

### Installing ha-rce-pse

1. **Add to HACS**:
   - Go to HACS → Integrations
   - Click "+" button
   - Search for "RCE PSE"
   - Install ha-rce-pse

2. **Configure Integration**:
   - Go to Settings → Devices & Services
   - Click "+ ADD INTEGRATION"
   - Search for "RCE PSE"
   - Configure:
     - **Cheapest Hours Search**:
       - Start hour: `00:00` (full day search)
       - End hour: `23:59`
       - Duration: 3-6 hours (based on battery capacity)
     - **Expensive Hours Search**:
       - Start hour: `06:00` (morning window)
       - End hour: `20:00` (daytime/evening window)
       - Duration: 1-2 hours (for sell windows)
     - **Hourly Price Averaging**: Enable if needed

3. **Verify Installation**:
   - Check that sensors appear under "RCE PSE" integration
   - Verify sensors are updating (check last_updated attribute)

## Sensor Mapping

### Price Sensors

| Old Sensor (Energy Optimizer YAML) | ha-rce-pse Sensor | Description |
|-----------------------------------|-------------------|-------------|
| `sensor.rce_prices_today` | `sensor.rce_pse_price` | Current price + full daily prices in `attributes.prices` |
| `sensor.current_rce_price` | `sensor.rce_pse_price` | Current hourly RCE price (state value) |
| `sensor.rce_prices_tomorrow` | `sensor.rce_pse_tomorrow_price` | Tomorrow prices in attributes (after 14:00 CET) |
| N/A | `sensor.rce_pse_next_hour_price` | Next hour price forecast |
| N/A | `sensor.rce_pse_price_2h` | Price in 2 hours |
| N/A | `sensor.rce_pse_price_3h` | Price in 3 hours |
| N/A | `sensor.rce_pse_previous_hour_price` | Previous hour price |

### Price Statistics Sensors

| Statistic | ha-rce-pse Sensor | Unit |
|-----------|-------------------|------|
| Today Average | `sensor.rce_pse_today_average_price` | PLN/MWh |
| Today Maximum | `sensor.rce_pse_today_max_price` | PLN/MWh |
| Today Minimum | `sensor.rce_pse_today_min_price` | PLN/MWh |
| Today Median | `sensor.rce_pse_today_median_price` | PLN/MWh |
| Tomorrow Average | `sensor.rce_pse_tomorrow_average_price` | PLN/MWh |
| Tomorrow Maximum | `sensor.rce_pse_tomorrow_max_price` | PLN/MWh |
| Tomorrow Minimum | `sensor.rce_pse_tomorrow_min_price` | PLN/MWh |
| Tomorrow Median | `sensor.rce_pse_tomorrow_median_price` | PLN/MWh |
| Price vs Today Avg | `sensor.rce_pse_price_comparison_to_today_average` | % |
| Price vs Tomorrow Avg | `sensor.rce_pse_price_comparison_to_tomorrow_average` | % |

### Time Range Sensors

| Purpose | ha-rce-pse Sensor | Format |
|---------|-------------------|--------|
| Max price hour start | `sensor.rce_pse_today_max_price_hour_start` | ISO timestamp |
| Max price hour end | `sensor.rce_pse_today_max_price_hour_end` | ISO timestamp |
| Max price hour range | `sensor.rce_pse_today_max_price_hour_range` | "HH:MM - HH:MM" |
| Min price hour start | `sensor.rce_pse_today_min_price_hour_start` | ISO timestamp |
| Min price hour end | `sensor.rce_pse_today_min_price_hour_end` | ISO timestamp |
| Min price hour range | `sensor.rce_pse_today_min_price_hour_range` | "HH:MM - HH:MM" |

### Custom Window Sensors (Configurable)

| Old Python Script | ha-rce-pse Sensor | Configurable Parameters |
|------------------|-------------------|------------------------|
| `find_prices_window_daytime.py` (lowest) | `sensor.rce_pse_today_cheapest_window_start` | Duration, search hours |
| `find_prices_window_daytime.py` (lowest) | `sensor.rce_pse_today_cheapest_window_end` | Duration, search hours |
| `find_prices_window_daytime.py` (lowest) | `sensor.rce_pse_today_cheapest_window_range` | Duration, search hours |
| `find_prices_window_daytime.py` (highest) | `sensor.rce_pse_today_expensive_window_start` | Duration, search hours |
| `find_prices_window_daytime.py` (highest) | `sensor.rce_pse_today_expensive_window_end` | Duration, search hours |
| `find_prices_window_daytime.py` (highest) | `sensor.rce_pse_today_expensive_window_range` | Duration, search hours |
| `find_prices_window_tomorrow_morning.py` | `sensor.rce_pse_tomorrow_cheapest_window_start` | Duration, search hours |
| `find_prices_window_tomorrow_morning.py` | `sensor.rce_pse_tomorrow_cheapest_window_end` | Duration, search hours |
| `find_prices_window_tomorrow_morning.py` | `sensor.rce_pse_tomorrow_cheapest_window_range` | Duration, search hours |
| N/A | `sensor.rce_pse_tomorrow_expensive_window_start` | Duration, search hours |
| N/A | `sensor.rce_pse_tomorrow_expensive_window_end` | Duration, search hours |
| N/A | `sensor.rce_pse_tomorrow_expensive_window_range` | Duration, search hours |

### Binary Sensors for Automation Triggers

| Purpose | ha-rce-pse Binary Sensor | Usage |
|---------|-------------------------|-------|
| Minimum price window active | `binary_sensor.rce_pse_today_min_price_window_active` | Trigger battery charging |
| Maximum price window active | `binary_sensor.rce_pse_today_max_price_window_active` | Trigger grid selling |
| Custom cheapest window active | `binary_sensor.rce_pse_today_cheapest_window_active` | Configurable window automation |
| Custom expensive window active | `binary_sensor.rce_pse_today_expensive_window_active` | Configurable window automation |

## Integration Architecture

### manifest.json Dependencies

```json
{
  "domain": "energy_optimizer",
  "name": "Energy Optimizer",
  "version": "1.0.0",
  "documentation": "https://github.com/YOUR_USERNAME/energy-optimizer",
  "requirements": [],
  "dependencies": ["template"],
  "after_dependencies": ["rce_pse", "solcast_solar"],
  "config_flow": true,
  "quality_scale": "bronze",
  "iot_class": "calculated"
}
```

**Key Points**:
- `rce_pse` is the domain of ha-rce-pse integration
- Listed in `after_dependencies` (loads after ha-rce-pse)
- `solcast_solar` is optional (for PV forecasting)

### Config Flow Validation

In `config_flow.py`, validate ha-rce-pse is installed:

```python
async def async_step_user(self, user_input=None):
    """Handle the initial step."""
    errors = {}
    
    if user_input is not None:
        # Check if ha-rce-pse integration is loaded
        if "rce_pse" not in self.hass.config.entries.async_domains():
            errors["base"] = "rce_pse_not_installed"
        else:
            # Check if ha-rce-pse sensors exist
            price_sensor = self.hass.states.get("sensor.rce_pse_price")
            if price_sensor is None:
                errors["base"] = "rce_pse_sensors_not_available"
            else:
                # Proceed with configuration
                return await self.async_step_battery()
    
    return self.async_show_form(
        step_id="user",
        data_schema=vol.Schema({}),
        errors=errors
    )
```

### strings.json Error Messages

```json
{
  "config": {
    "error": {
      "rce_pse_not_installed": "ha-rce-pse integration not found. Please install it from HACS first.",
      "rce_pse_sensors_not_available": "ha-rce-pse sensors not available. Check integration configuration."
    }
  }
}
```

## Using ha-rce-pse Sensors in Energy Optimizer

### Example: Battery Charging Decision

```python
from homeassistant.helpers.update_coordinator import CoordinatorEntity

class EnergyOptimizerSensor(CoordinatorEntity):
    """Energy Optimizer sensor that uses ha-rce-pse data."""
    
    async def async_update(self):
        """Update sensor using ha-rce-pse price data."""
        # Get current RCE price from ha-rce-pse
        price_sensor = self.hass.states.get("sensor.rce_pse_price")
        current_price = float(price_sensor.state) if price_sensor else None
        
        # Get today's average price
        avg_sensor = self.hass.states.get("sensor.rce_pse_today_average_price")
        avg_price = float(avg_sensor.state) if avg_sensor else None
        
        # Get cheapest window for charging
        window_start = self.hass.states.get("sensor.rce_pse_today_cheapest_window_start")
        window_end = self.hass.states.get("sensor.rce_pse_today_cheapest_window_end")
        
        # Use these values in battery calculations
        if current_price and avg_price:
            if current_price < avg_price * 0.8:  # 20% below average
                # Recommend charging
                self._attr_native_value = "charge"
            else:
                self._attr_native_value = "hold"
```

### Example: Automation with Binary Sensors

```yaml
automation:
  - alias: "Charge Battery During Cheapest Window"
    trigger:
      - platform: state
        entity_id: binary_sensor.rce_pse_today_cheapest_window_active
        to: "on"
    condition:
      - condition: numeric_state
        entity_id: sensor.battery_soc
        below: 80
    action:
      - service: number.set_value
        target:
          entity_id: number.inverter_target_soc
        data:
          value: 100
```

### Example: Service Using Price Data

```python
async def async_calculate_charge_soc(self, call):
    """Service to calculate optimal charge SOC using ha-rce-pse data."""
    # Get price data from ha-rce-pse
    price_sensor = self.hass.states.get("sensor.rce_pse_price")
    prices_attr = price_sensor.attributes.get("prices", [])
    
    # Get today's statistics
    avg_price = float(self.hass.states.get("sensor.rce_pse_today_average_price").state)
    min_price = float(self.hass.states.get("sensor.rce_pse_today_min_price").state)
    
    # Get cheapest window
    cheapest_start = self.hass.states.get("sensor.rce_pse_today_cheapest_window_start").state
    cheapest_end = self.hass.states.get("sensor.rce_pse_today_cheapest_window_end").state
    
    # Calculate optimal SOC based on price data
    # ... calculation logic ...
    
    return {
        "target_soc": calculated_soc,
        "cheapest_window_start": cheapest_start,
        "cheapest_window_end": cheapest_end,
        "expected_savings": savings_pln
    }
```

## Migration from Python Scripts

### Old Approach (Python Scripts)

```yaml
# python_scripts/find_prices_window_daytime.py
# Complex logic to find optimal windows

automation:
  - alias: "Find Price Windows"
    trigger:
      - platform: time
        at: "14:00:00"
    action:
      - service: python_script.find_prices_window_daytime
        data:
          prices_entity: sensor.rce_prices_tomorrow
```

### New Approach (ha-rce-pse)

```yaml
# Configuration in ha-rce-pse integration UI
# Set window search parameters once

automation:
  - alias: "Charge During Tomorrow's Cheapest Window"
    trigger:
      - platform: state
        entity_id: binary_sensor.rce_pse_today_cheapest_window_active
        to: "on"
    action:
      # Direct action, no script needed
      - service: energy_optimizer.calculate_charge_soc
```

**Benefits**:
- ✓ No Python script maintenance
- ✓ UI-configurable window parameters
- ✓ Real-time binary sensors for triggers
- ✓ Automatic updates every 30 minutes
- ✓ Built-in error handling and logging

## Configuration Recommendations

### For Current Energy Optimizer Use Case

Based on the analyzed automations:

1. **Cheapest Window (Grid Charging)**:
   - **Purpose**: Find lowest price period for battery charging
   - **Search Start**: `00:00` (full day)
   - **Search End**: `23:59`
   - **Duration**: 3-6 hours (based on battery capacity and typical charging rate)
   - **Use Sensor**: `sensor.rce_pse_today_cheapest_window_start/end`
   - **Trigger**: `binary_sensor.rce_pse_today_cheapest_window_active`

2. **Expensive Window (Grid Selling)**:
   - **Purpose**: Find highest price period for selling battery energy
   - **Search Start**: `06:00` (morning)
   - **Search End**: `20:00` (evening)
   - **Duration**: 1-2 hours (typical peak duration)
   - **Use Sensor**: `sensor.rce_pse_today_expensive_window_start/end`
   - **Trigger**: `binary_sensor.rce_pse_today_expensive_window_active`

3. **Tomorrow Morning Window**:
   - **Purpose**: Plan next day's morning charging
   - **Use Sensor**: `sensor.rce_pse_tomorrow_cheapest_window_start/end`
   - **Available**: After 14:00 CET
   - **Automation**: Update `input_datetime` helpers at 14:00

### Dynamic Window Duration

For PV capacity-based window sizing (currently in Python script):

```python
def calculate_optimal_duration(pv_peak_forecast_kwh: float, battery_capacity_kwh: float) -> int:
    """Calculate optimal charging window duration based on PV forecast."""
    if pv_peak_forecast_kwh < 5:
        return 6  # Longer window for low PV days
    elif pv_peak_forecast_kwh < 10:
        return 4  # Medium window
    else:
        return 3  # Shorter window for high PV days
```

**Implementation Options**:
1. Create multiple ha-rce-pse configurations with different durations
2. Use Energy Optimizer service to select appropriate window sensor based on PV forecast
3. Reconfigure ha-rce-pse duration via automation when PV forecast available

## Testing Checklist

### Integration Tests

- [ ] Energy Optimizer loads successfully with ha-rce-pse installed
- [ ] Config flow validates ha-rce-pse presence correctly
- [ ] Config flow shows error when ha-rce-pse not installed
- [ ] Sensors update when ha-rce-pse sensors change
- [ ] Services receive correct price data from ha-rce-pse

### Functional Tests

- [ ] Battery charging triggers during cheapest window
- [ ] Grid selling triggers during expensive window
- [ ] Tomorrow's window planning works after 14:00
- [ ] Binary sensors trigger automations correctly
- [ ] Price comparison calculations use correct ha-rce-pse statistics

### Edge Cases

- [ ] Handle ha-rce-pse sensor unavailable (API failure)
- [ ] Handle missing tomorrow data before 14:00
- [ ] Handle ha-rce-pse integration uninstalled after Energy Optimizer setup
- [ ] Graceful degradation when ha-rce-pse sensors return `unknown`

## Documentation Updates Required

### README.md

```markdown
## Prerequisites

Before installing Energy Optimizer, you must install:

1. **ha-rce-pse** (REQUIRED)
   - Repository: https://github.com/Lewa-Reka/ha-rce-pse
   - Install via HACS
   - Provides all RCE price data and price window calculations
   - Configuration guide: [ha-rce-pse setup](docs/ha-rce-pse-setup.md)

2. **Solcast Solar** (OPTIONAL)
   - For PV production forecasting
   - Install via HACS

## Installation

1. Install ha-rce-pse from HACS
2. Configure ha-rce-pse with your window search parameters
3. Install Energy Optimizer from HACS
4. Configure Energy Optimizer integration
```

### TROUBLESHOOTING.md

```markdown
## ha-rce-pse Integration Issues

### Error: "rce_pse_not_installed"

**Cause**: ha-rce-pse integration not installed or not loaded

**Solution**:
1. Install ha-rce-pse from HACS
2. Restart Home Assistant
3. Verify integration shows in Settings → Devices & Services
4. Try configuring Energy Optimizer again

### Error: "rce_pse_sensors_not_available"

**Cause**: ha-rce-pse sensors not creating or not updating

**Solution**:
1. Check ha-rce-pse integration configuration
2. Verify internet connection (PSE API access)
3. Check ha-rce-pse logs for errors
4. Restart ha-rce-pse integration
5. Wait 30 minutes for first sensor update

### Sensors Show "Unknown"

**Possible Causes**:
- PSE API temporarily unavailable
- Before 14:00 for tomorrow sensors
- Integration just installed (wait for first update)

**Solution**:
- Check ha-rce-pse integration logs
- Verify PSE API status
- Wait for next 30-minute update cycle
```

## Summary

### Integration Dependencies

**Energy Optimizer depends on:**
1. ✓ **ha-rce-pse** (domain: `rce_pse`) - Provides ALL RCE price and window functionality
   - Repository: https://github.com/Lewa-Reka/ha-rce-pse
   - Sensors: Prices, statistics, configurable time windows, binary sensors

2. ✓ **ha-solarman** (domain: `solarman`) - Provides inverter and battery control entities
   - Repository: https://github.com/davidrapan/ha-solarman
   - Entities: Number (SOC target, charging current), Select (work mode), Sensor (battery SOC, power)
   - Supports: Deye, Solis, Solax, Sofar, and other Solarman-compatible inverters

3. ⚠️ **Solcast PV Forecast** (domain: `solcast_solar`) - Optional PV forecasting
   - Repository: https://github.com/BJReplay/ha-solcast-solar
   - Provides: Daily forecasts, peak forecasts, detailed breakdown attributes

### What Energy Optimizer Does NOT Need to Implement

✓ **RCE Price Fetching** - ha-rce-pse handles this
✓ **Price Window Calculations** - ha-rce-pse provides configurable windows
✓ **PSE API Client** - ha-rce-pse manages API communication
✓ **Price Statistics** - ha-rce-pse calculates average/min/max/median
✓ **Binary Sensors for Windows** - ha-rce-pse provides trigger sensors
✓ **Inverter Modbus Communication** - ha-solarman handles inverter control
✓ **Inverter Entity Platform** - ha-solarman provides number/select/sensor entities

### What Energy Optimizer SHOULD Focus On

- Battery optimization calculations (SOC, reserve, space, charging current)
- Heat pump energy estimation (COP-based, temperature interpolation)
- Energy balance calculations (required energy, surplus/deficit)
- Automation coordination (using ha-rce-pse binary sensors + ha-solarman control entities)
- Services for on-demand calculations that combine price data with battery/load data
- UI-based configuration for user preferences

### Architecture Benefits

1. **Separation of Concerns**: Energy Optimizer focuses on optimization logic, not data fetching or device control
2. **Reusability**: ha-rce-pse and ha-solarman can be used by other integrations
3. **Maintainability**: PSE API changes handled by ha-rce-pse team, inverter protocols by ha-solarman team
4. **Configurability**: Users can adjust window parameters and inverter settings without code changes
5. **Reliability**: Proven, tested integrations for RCE data and inverter control
6. **Community**: Leverage existing community integrations and support
7. **Device Independence**: ha-solarman supports multiple inverter brands via definition files

## Next Steps

1. ✓ Update Energy Optimizer research document with ha-rce-pse sensor mappings
2. ✓ Update Energy Optimizer research document with ha-solarman entity mappings
3. ✓ Remove plans to implement RCE fetching and window calculations
4. ✓ Remove plans to implement inverter entity platforms
5. Update manifest.json to include `rce_pse` and `solarman` in `after_dependencies`
6. Implement config flow validation for ha-rce-pse and ha-solarman presence
7. Create migration guide mapping old sensors to ha-rce-pse/ha-solarman entities
8. Write integration tests with ha-rce-pse and ha-solarman mock entities
9. Document ha-rce-pse and ha-solarman configuration requirements in README
