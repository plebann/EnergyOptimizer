<!-- markdownlint-disable-file -->
# Solcast PV Forecast Integration Guide for Energy Optimizer

## Overview

This document provides guidance on integrating **Solcast PV Forecast** (domain: `solcast_solar`) with the Energy Optimizer HACS integration. The Solcast integration provides solar PV generation forecasts from the Solcast API service.

**Repository**: https://github.com/BJReplay/ha-solcast-solar  
**Version Analyzed**: v4.4.10  
**API Service**: Solcast.com (hobbyist: 10 API calls/day, original users: 50 calls/day)  
**Update Frequency**: Configurable auto-update or manual automation  
**Forecast Horizon**: Up to 14 days (7 days exposed as sensors)

## Prerequisites

### Solcast Account Setup

1. **Sign up for Solcast**:
   - Visit https://solcast.com/
   - Create hobbyist account (free tier)
   - Wait up to 24 hours for account activation
   - Get API key from https://toolkit.solcast.com.au/account

2. **Configure Rooftop Sites**:
   - Add your solar installation(s) at solcast.com
   - **Critical**: Set azimuth correctly
     - Azimuth is degrees from North (not South!)
     - West: 0° to 180°
     - East: 0° to -179°
   - Set tilt angle accurately
   - Set capacity (AC and DC)
   - Maximum 2 sites for free hobbyist account

3. **Verify Configuration**:
   - Remove any sample sites from dashboard
   - Confirm azimuth sign (West=positive, East=negative)
   - Double-check tilt matches actual installation

### Installing Solcast PV Forecast

1. **Add to HACS**:
   - Go to HACS → Integrations
   - Search for "Solcast PV Forecast"
   - Install integration by BJReplay
   - Restart Home Assistant

2. **Configure Integration**:
   - Settings → Devices & Services → Add Integration
   - Search for "Solcast PV Forecast"
   - Enter:
     - **API Key**: From Solcast account
     - **API Limit**: 10 (new users) or 50 (original users)
     - **Auto-update**: Enable for automatic forecast updates
   - Multiple API keys: Separate with comma if >2 sites
   - Click Submit

3. **Verify Installation**:
   - Check that sensors appear
   - Verify `sensor.solcast_pv_forecast_forecast_today` updating
   - Check Energy dashboard configuration

## Sensors Provided by Solcast

### Daily Forecast Sensors

| Sensor Entity ID | Unit | Description | Attributes |
|-----------------|------|-------------|------------|
| `sensor.solcast_pv_forecast_forecast_today` | kWh | Total forecast for today | detailedForecast (half-hourly), detailedHourly |
| `sensor.solcast_pv_forecast_forecast_tomorrow` | kWh | Total forecast for tomorrow | detailedForecast, detailedHourly |
| `sensor.solcast_pv_forecast_forecast_day_3` | kWh | Forecast for day+2 | detailedForecast, detailedHourly (disabled by default) |
| `sensor.solcast_pv_forecast_forecast_day_4` | kWh | Forecast for day+3 | detailedForecast, detailedHourly (disabled by default) |
| `sensor.solcast_pv_forecast_forecast_day_5` | kWh | Forecast for day+4 | detailedForecast, detailedHourly (disabled by default) |
| `sensor.solcast_pv_forecast_forecast_day_6` | kWh | Forecast for day+5 | detailedForecast, detailedHourly (disabled by default) |
| `sensor.solcast_pv_forecast_forecast_day_7` | kWh | Forecast for day+6 | detailedForecast, detailedHourly (disabled by default) |

### Real-Time Forecast Sensors

| Sensor Entity ID | Unit | Description | Site Breakdown |
|-----------------|------|-------------|----------------|
| `sensor.solcast_pv_forecast_forecast_this_hour` | Wh | Forecast for current hour | Yes (attributes) |
| `sensor.solcast_pv_forecast_forecast_next_hour` | Wh | Forecast for next hour | Yes (attributes) |
| `sensor.solcast_pv_forecast_forecast_next_x_hours` | Wh | Custom duration forecast | Yes (disabled by default) |
| `sensor.solcast_pv_forecast_forecast_remaining_today` | kWh | Remaining forecast today | No |

### Peak Forecast Sensors

| Sensor Entity ID | Unit | Description | Site Breakdown |
|-----------------|------|-------------|----------------|
| `sensor.solcast_pv_forecast_peak_forecast_today` | W | Peak power forecast today | Yes (attributes) |
| `sensor.solcast_pv_forecast_peak_time_today` | datetime | Time of peak today | Yes (attributes) |
| `sensor.solcast_pv_forecast_peak_forecast_tomorrow` | W | Peak power forecast tomorrow | Yes (attributes) |
| `sensor.solcast_pv_forecast_peak_time_tomorrow` | datetime | Time of peak tomorrow | Yes (attributes) |

### Power Forecast Sensors

| Sensor Entity ID | Unit | Description | Site Breakdown |
|-----------------|------|-------------|----------------|
| `sensor.solcast_pv_forecast_power_now` | W | Forecast power right now | Yes (attributes) |
| `sensor.solcast_pv_forecast_power_in_30_minutes` | W | Forecast power in 30 min | Yes (attributes) |
| `sensor.solcast_pv_forecast_power_in_1_hour` | W | Forecast power in 1 hour | Yes (attributes) |

### Diagnostic Sensors

| Sensor Entity ID | Description |
|-----------------|-------------|
| `sensor.solcast_pv_forecast_api_last_polled` | Last successful API update datetime |
| `sensor.solcast_pv_forecast_api_limit` | Total API calls allowed per day |
| `sensor.solcast_pv_forecast_api_used` | API calls used today (resets midnight UTC) |
| `sensor.solcast_pv_forecast_dampening` | Dampening status (enabled/disabled) |
| `sensor.solcast_pv_forecast_hard_limit_set` | Hard limit in kW (false if not set) |

### Per-Rooftop Sensors

| Sensor Entity ID Pattern | Unit | Description |
|--------------------------|------|-------------|
| `sensor.solcast_pv_forecast_{site_name}` | kWh | Today's forecast for specific site |

## Sensor Attributes

### Forecast Confidence Levels

All forecast sensors include three confidence level attributes:
- `estimate10`: 10th percentile (worst case, cloudy)
- `estimate`: 50th percentile (most likely)
- `estimate90`: 90th percentile (best case, clear)

**Access in templates**:
```yaml
{{ state_attr('sensor.solcast_pv_forecast_forecast_today', 'estimate10') | float(0) }}
{{ state_attr('sensor.solcast_pv_forecast_forecast_today', 'estimate') | float(0) }}
{{ state_attr('sensor.solcast_pv_forecast_forecast_today', 'estimate90') | float(0) }}
```

### Per-Site Breakdown

Sensors with site breakdown include attributes named after site resource ID (hyphens → underscores):
- `1234_5678_9012_3456`: Site portion of total (kWh/W/Wh)
- `estimate10_1234_5678_9012_3456`: 10th percentile for site
- `estimate_1234_5678_9012_3456`: 50th percentile for site
- `estimate90_1234_5678_9012_3456`: 90th percentile for site

**Example**:
```yaml
{{ state_attr('sensor.solcast_pv_forecast_peak_forecast_today', '1234_5678_9012_3456') | float(0) }}
```

### Detailed Forecast Attributes

Daily forecast sensors include detailed breakdown attributes:

**`detailedForecast`**: Half-hourly power forecast (list of dicts)
```yaml
- period_start: '2025-12-19T08:00:00+01:00'
  pv_estimate10: 0.5
  pv_estimate: 1.2
  pv_estimate90: 2.0
- period_start: '2025-12-19T08:30:00+01:00'
  pv_estimate10: 0.8
  pv_estimate: 1.5
  pv_estimate90: 2.3
...
```

**`detailedHourly`**: Hourly power forecast (list of dicts)
```yaml
- period_start: '2025-12-19T08:00:00+01:00'
  pv_estimate10: 0.6
  pv_estimate: 1.3
  pv_estimate90: 2.1
...
```

**Units**: Values in detailed forecasts are **kW** (average power for period), not kWh.

### Site-Specific Detailed Attributes

If per-site breakdown enabled:
- `detailedForecast_1234_5678_9012_3456`: Half-hourly for specific site
- `detailedHourly_1234_5678_9012_3456`: Hourly for specific site

## Energy Optimizer Integration

### Config Flow Sensor Selection

Energy Optimizer should allow users to select Solcast sensors:

```python
STEP_PV_SCHEMA = vol.Schema({
    vol.Optional("pv_forecast_today"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            integration="solcast_solar"
        )
    ),
    vol.Optional("pv_peak_forecast_today"): selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain="sensor",
            integration="solcast_solar"
        )
    ),
})
```

### Dynamic Window Sizing Example

Use PV forecast to adjust charging window duration:

```python
async def calculate_charging_window_duration(self, hass):
    """Calculate optimal charging window based on PV forecast."""
    # Get tomorrow's PV forecast
    pv_forecast_tomorrow = hass.states.get("sensor.solcast_pv_forecast_forecast_tomorrow")
    
    if not pv_forecast_tomorrow:
        return 6  # Default: 6-hour window
    
    forecast_kwh = float(pv_forecast_tomorrow.state)
    battery_capacity_kwh = 9.6  # Example: 200Ah * 48V / 1000
    
    # Calculate window duration based on expected PV generation
    if forecast_kwh < 5:
        # Low PV: Need longer grid charging window
        return 6
    elif forecast_kwh < 10:
        # Medium PV: Moderate window
        return 4
    else:
        # High PV: Short window, PV will supplement
        return 3
```

### Surplus Energy Calculation Example

Use PV forecast to determine sellable surplus:

```python
async def calculate_sellable_surplus(self, hass):
    """Calculate available surplus considering PV forecast."""
    # Get battery state
    battery_soc = float(hass.states.get("sensor.deye_hybrid_battery_soc").state)
    battery_capacity_ah = float(hass.states.get("number.deye_hybrid_battery_capacity").state)
    battery_voltage = 48
    min_soc = 10
    
    # Get PV forecast remaining today
    pv_remaining = float(hass.states.get("sensor.solcast_pv_forecast_forecast_remaining_today").state)
    
    # Get load forecast (simplified)
    expected_load_kwh = 5.0  # Could be calculated from historical data
    
    # Calculate available battery energy above reserve
    available_battery_kwh = ((battery_soc - min_soc) / 100) * (battery_capacity_ah * battery_voltage / 1000)
    
    # Calculate total available energy
    total_available = available_battery_kwh + pv_remaining
    
    # Calculate surplus after covering expected load
    surplus_kwh = max(0, total_available - expected_load_kwh)
    
    return {
        "surplus_kwh": surplus_kwh,
        "battery_kwh": available_battery_kwh,
        "pv_remaining_kwh": pv_remaining,
        "expected_load_kwh": expected_load_kwh
    }
```

### Service Using Detailed Forecast

Access half-hourly forecast data:

```python
async def get_peak_pv_hours(self, hass, date_str="today"):
    """Get hours with peak PV production."""
    sensor_entity = f"sensor.solcast_pv_forecast_forecast_{date_str}"
    forecast_sensor = hass.states.get(sensor_entity)
    
    if not forecast_sensor:
        return []
    
    detailed_forecast = forecast_sensor.attributes.get("detailedForecast", [])
    
    # Find peak hours (>= 80% of daily peak)
    peak_power = max(period["pv_estimate"] for period in detailed_forecast)
    threshold = peak_power * 0.8
    
    peak_hours = []
    for period in detailed_forecast:
        if period["pv_estimate"] >= threshold:
            hour = period["period_start"][11:16]  # Extract HH:MM
            peak_hours.append(hour)
    
    return peak_hours
```

## Blueprint Example

Automation that adjusts battery target based on PV forecast:

```yaml
blueprint:
  name: Energy Optimizer - PV-Aware Charging
  description: Adjust battery charge target based on tomorrow's PV forecast
  domain: automation
  input:
    pv_forecast_sensor:
      name: Tomorrow PV Forecast
      selector:
        entity:
          domain: sensor
          integration: solcast_solar
    battery_capacity_kwh:
      name: Battery Capacity
      selector:
        number:
          min: 1
          max: 50
          unit_of_measurement: kWh
      default: 10

trigger:
  - platform: time
    at: "14:00:00"  # After tomorrow's forecast available

action:
  - variables:
      pv_forecast: "{{ states(pv_forecast_sensor) | float(0) }}"
      battery_capacity: "{{ battery_capacity_kwh }}"
      
      # Calculate target SOC based on PV forecast
      # Low PV = charge to 100%, High PV = charge to 60%
      target_soc: >
        {% if pv_forecast < 5 %}
          100
        {% elif pv_forecast < 10 %}
          80
        {% else %}
          60
        {% endif %}
  
  - service: energy_optimizer.calculate_charge_soc
    data:
      override_target_soc: "{{ target_soc }}"
  
  - service: notify.persistent_notification
    data:
      title: "Battery Target Adjusted"
      message: "PV forecast: {{ pv_forecast }} kWh | Target SOC: {{ target_soc }}%"
```

## Advanced Features

### Dampening Configuration

Solcast supports forecast dampening to account for shading:
- **Automated dampening**: Compare actual vs estimated actual generation
- **Manual hourly dampening**: Set factors for each hour (0.0-1.0)
- **Granular dampening**: Half-hourly or per-site dampening

**Energy Optimizer Use**: If user has shading issues, can leverage Solcast dampening instead of implementing custom shading logic.

### Hard Limit Configuration

For over-sized PV systems where inverter limits generation:
- Set hard limit in kW
- Clips forecasts to maximum inverter output

**Energy Optimizer Use**: Accurate forecasts for over-sized arrays.

### Excluded Sites

Exclude specific Solcast sites from totals:
- Useful for remote sites
- Can build separate template sensors for excluded sites

**Energy Optimizer Use**: Handle multiple properties with separate optimizations.

## Testing Strategy

### Manual Testing

- [ ] Solcast integration installed and configured
- [ ] API key valid and sensors updating
- [ ] Daily forecast sensors showing reasonable values
- [ ] Peak forecast matches expected solar production
- [ ] detailedForecast attribute populated
- [ ] Energy Optimizer can read Solcast sensor states
- [ ] Energy Optimizer services use PV forecast in calculations

### Integration Testing

```python
async def test_solcast_sensor_read(hass):
    """Test reading Solcast forecast sensor."""
    # Mock Solcast sensor
    hass.states.async_set(
        "sensor.solcast_pv_forecast_forecast_today",
        "12.5",
        attributes={
            "estimate": 12.5,
            "estimate10": 10.2,
            "estimate90": 14.8,
            "detailedForecast": [
                {"period_start": "2025-12-19T08:00:00+01:00", "pv_estimate": 1.2},
                {"period_start": "2025-12-19T08:30:00+01:00", "pv_estimate": 1.5},
            ]
        }
    )
    
    # Call Energy Optimizer service
    response = await hass.services.async_call(
        "energy_optimizer",
        "calculate_charging_window_duration",
        blocking=True,
        return_response=True
    )
    
    # Verify PV forecast used in calculation
    assert response["pv_forecast_kwh"] == 12.5
    assert response["window_duration_hours"] == 4  # Medium PV = 4 hours
```

## Common Sensor Mappings

### Old YAML → Solcast Entities

| Old Entity/Config | Solcast Sensor | Notes |
|------------------|----------------|-------|
| PV forecast today | `sensor.solcast_pv_forecast_forecast_today` | Direct mapping |
| PV forecast tomorrow | `sensor.solcast_pv_forecast_forecast_tomorrow` | Available after ~14:00 |
| Peak production time | `sensor.solcast_pv_forecast_peak_time_today` | Datetime value |
| Peak production power | `sensor.solcast_pv_forecast_peak_forecast_today` | In watts |
| Remaining today | `sensor.solcast_pv_forecast_forecast_remaining_today` | Updates throughout day |

### Entity Discovery in Config Flow

```python
async def async_step_pv_forecast(self, user_input=None):
    """Select PV forecast sensors."""
    errors = {}
    
    if user_input is not None:
        return self.async_create_entry(title="Energy Optimizer", data=user_input)
    
    # Find Solcast sensors
    entity_registry = er.async_get(self.hass)
    solcast_sensors = {
        entry.entity_id: entry
        for entry in entity_registry.entities.values()
        if entry.platform == "solcast_solar" and entry.domain == "sensor"
    }
    
    # Filter by sensor type
    forecast_today_sensors = [
        entity_id for entity_id in solcast_sensors
        if "forecast_today" in entity_id
    ]
    
    return self.async_show_form(
        step_id="pv_forecast",
        data_schema=vol.Schema({
            vol.Optional("pv_forecast_today", default=forecast_today_sensors[0] if forecast_today_sensors else None): vol.In(forecast_today_sensors),
        }),
        errors=errors
    )
```

## Troubleshooting

### Issue: Solcast sensors unavailable

**Cause**: API call failures or rate limiting

**Solution**:
1. Check Solcast API limit (10/day for new hobbyist)
2. Verify API key correct
3. Check Solcast service status
4. Review integration logs for 429/Too Busy errors
5. Wait for next auto-update cycle

### Issue: Forecast values seem incorrect

**Cause**: Rooftop site misconfiguration (azimuth/tilt)

**Solution**:
1. Verify azimuth sign (West=positive, East=negative)
2. Double-check tilt angle
3. Confirm capacity values (AC vs DC)
4. Compare forecast to actual on clear day
5. Check for unusual azimuth warning in logs

### Issue: detailedForecast attribute empty

**Cause**: Attribute disabled in integration options

**Solution**:
1. Go to Solcast integration → CONFIGURE
2. Enable "Sensor attributes configuration"
3. Enable "Detailed half-hourly breakdown"
4. Restart integration

## Documentation Requirements

### README.md

```markdown
## Prerequisites

3. **Solcast PV Forecast** (OPTIONAL - for PV-aware optimization)
   - Repository: https://github.com/BJReplay/ha-solcast-solar
   - Install via HACS
   - Requires Solcast.com hobbyist account (free)
   - Configure rooftop sites at solcast.com
   - Provides solar production forecasts for intelligent charging
```

### CONFIGURATION.md

```markdown
## PV Forecast Configuration (Optional)

If you have solar panels and want PV-aware battery optimization:

1. **Install Solcast PV Forecast**:
   - Install from HACS
   - Create account at solcast.com
   - Configure rooftop sites (azimuth, tilt, capacity)
   - Enter API key in integration config

2. **Energy Optimizer Setup**:
   - During config flow, select PV forecast sensors
   - Typically: `sensor.solcast_pv_forecast_forecast_today`
   - Energy Optimizer will adjust strategies based on forecast
   - Example: Charge less from grid if high PV expected

3. **Benefits**:
   - Dynamic charging window sizing
   - Surplus energy calculation considers PV
   - Avoid over-charging when sunny day expected
```

## Summary

### Solcast PV Forecast Provides

✓ **Daily Forecasts** - Today through day+7 (kWh)
✓ **Peak Forecasts** - Peak power and time for today/tomorrow
✓ **Real-Time Forecasts** - Current hour, next hour, next X hours
✓ **Detailed Attributes** - Half-hourly and hourly breakdowns
✓ **Confidence Levels** - estimate10/estimate/estimate90
✓ **Per-Site Breakdown** - Individual rooftop forecasts
✓ **Energy Dashboard** - Integration with HA Energy dashboard
✓ **Dampening Support** - Automated or manual shading adjustment
✓ **Hard Limit** - Inverter capacity limiting for over-sized arrays

### Energy Optimizer Should

- **Reference** Solcast sensors in config flow (optional)
- **Read** PV forecasts for intelligent optimization
- **Calculate** dynamic charging windows based on PV
- **Determine** surplus energy including PV remaining
- **Adjust** strategies (charge less if sunny day expected)
- **Provide** services that factor PV forecast into decisions
- **Support** operation without Solcast (graceful degradation)

### Architecture Integration

```
┌─────────────────────────┐
│   Solcast PV Forecast   │ ← PV Production Forecast
│   - Daily forecasts     │
│   - Peak forecasts      │
│   - Detailed breakdown  │
│   - Confidence levels   │
└──────────┬──────────────┘
           │
           ↓ provides forecasts
┌─────────────────────────┐
│   energy_optimizer      │ ← Optimization Engine
│   - Battery calcs       │
│   - PV-aware charging   │
│   - Surplus calcs       │
│   - Dynamic windows     │
└─────────────────────────┘
```

This optional integration enables:
- **Smarter Charging**: Charge less if sunny day forecasted
- **Better Timing**: Avoid expensive grid charging when PV will supplement
- **Surplus Accuracy**: Know what's available to sell (battery + PV remaining)
- **Dynamic Optimization**: Adjust strategy based on weather forecast
