# Energy Optimizer for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/plebann/EnergyOptimizer.svg)](https://github.com/plebann/EnergyOptimizer/releases)

Energy Optimizer is a Home Assistant custom integration that intelligently manages battery charging and energy optimization based on electricity prices, battery state, PV forecasts, and load patterns.

## Features

### 🔋 **Smart Battery Management**
- Automated battery charge/discharge scheduling based on price forecasts
- Multi-phase charging current calculation (23A → 9A → 4A)
- Battery health protection with configurable SOC limits
- Real-time battery reserve and space monitoring

### 💰 **Cost Optimization**
- Charge during cheap electricity periods
- Sell surplus energy during expensive periods
- Price-based decision making with configurable thresholds
- Integration with RCE PSE pricing data

### ☀️ **PV Forecast Integration**
- Solcast Solar integration for production forecasting
- Intelligent charging based on expected PV generation
- Surplus energy calculation considering future production

### 🌡️ **Heat Pump Support**
- Temperature-based consumption estimation
- COP curve interpolation for accurate forecasting
- Integration with energy balance calculations

### 📊 **Comprehensive Sensors**
- Battery Reserve, Space, Capacity sensors
- Required Energy (Morning, Afternoon, Evening)
- Surplus Energy calculation
- Heat Pump daily estimation

### 🔧 **Flexible Configuration**
- Entity-based configuration (no hard integration dependencies)
- 9-step guided configuration flow
- Compatible with any integration providing similar entities
- Reconfigurable via Options Flow

## Prerequisites

### Recommended Integrations

While Energy Optimizer can work with any compatible entities, these integrations are recommended:

1. **[ha-rce-pse](https://github.com/plewka/ha-rce-pse)** - RCE electricity pricing
   - Provides: Current price, average price, price windows
   - Install from HACS

2. **[ha-solarman](https://github.com/StephanJoubert/home_assistant_solarman)** - Inverter/battery control
   - Provides: Battery SOC, power, voltage, control entities
   - Install from HACS

3. **[Solcast Solar](https://github.com/BJReplay/ha-solcast-solar)** (Optional)
   - Provides: PV production forecasts
   - Install from HACS

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/plebann/EnergyOptimizer`
6. Select category: "Integration"
7. Click "Add"
8. Search for "Energy Optimizer" and install

### Manual Installation

1. Download the latest release from [GitHub](https://github.com/plebann/EnergyOptimizer/releases)
2. Extract the `custom_components/energy_optimizer` folder
3. Copy to your Home Assistant `config/custom_components/` directory
4. Restart Home Assistant

## Configuration

### Initial Setup

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for **Energy Optimizer**
4. Follow the 9-step configuration wizard:

#### Step 1: Welcome
- Read integration overview and recommendations

#### Step 2: Price Entities
- **Required**: Current price sensor, Average price sensor
- **Optional**: Cheapest/expensive window sensors, Tomorrow price sensor

#### Step 3: Battery Sensors
- **Required**: Battery SOC sensor, Battery power sensor
- **Optional**: Voltage sensor, Current sensor

#### Step 4: Battery Parameters
- **Capacity**: 200 Ah (default)
- **Voltage**: 48V (default)
- **Efficiency**: 95% (default)
- **Min/Max SOC**: 10% / 100% (default)

#### Step 5: Control Entities
- **Required**: Target SOC control entity
- **Optional**: Work mode, Charge/discharge current, Grid charge switch

#### Step 6: PV & Load Configuration
- **Optional**: Daily load sensor, PV forecast sensors, Weather entity

#### Step 7: Heat Pump Configuration
- **Optional**: Enable heat pump, Temperature sensor, Power sensor

#### Step 8: Review
- Verify all configured entities

### Example Entity Configuration

```yaml
# Price entities (ha-rce-pse)
price_sensor: sensor.rce_pse_price
average_price_sensor: sensor.rce_pse_today_average_price
cheapest_window_sensor: binary_sensor.rce_pse_today_cheapest_window_active
expensive_window_sensor: binary_sensor.rce_pse_today_expensive_window_active

# Battery sensors (ha-solarman)
battery_soc_sensor: sensor.deye_hybrid_battery_soc
battery_power_sensor: sensor.deye_hybrid_battery_power
battery_voltage_sensor: sensor.deye_hybrid_battery_voltage
battery_current_sensor: sensor.deye_hybrid_battery_current

# Control entities (ha-solarman)
target_soc_entity: number.deye_hybrid_max_soc
work_mode_entity: select.deye_hybrid_work_mode
charge_current_entity: number.deye_hybrid_max_charge_current

# PV forecast (Solcast Solar)
pv_forecast_today: sensor.solcast_pv_forecast_forecast_today
pv_forecast_tomorrow: sensor.solcast_pv_forecast_forecast_tomorrow
pv_forecast_remaining: sensor.solcast_pv_forecast_forecast_remaining_today
```

### Multi-Program Configuration (Solarman Inverters)

For Solarman-compatible inverters (DEYE/Sunsynk/SolArk) with multiple time-based charging programs, you can configure up to 6 programmable SOC targets instead of a single entity. The integration will automatically select the appropriate program entity based on the current time.

**When to Use Multi-Program Mode:**
- Your inverter supports time-slot based charging (common in DEYE/Sunsynk/SolArk)
- You want different SOC targets for different times of day
- You're using the Solarman integration which exposes program entities

**Configuration Example:**
```yaml
# Leave target_soc_entity empty or unconfigured

# Program 1 - Night charging (cheap electricity)
prog1_soc_entity: number.deye_hybrid_prog1_capacity
prog1_time_start: "22:00"
prog1_time_end: "06:00"

# Program 2 - Morning (after cheap tariff)
prog2_soc_entity: number.deye_hybrid_prog2_capacity
prog2_time_start: "06:00"
prog2_time_end: "10:00"

# Program 3 - Afternoon (peak solar)
prog3_soc_entity: number.deye_hybrid_prog3_capacity
prog3_time_start: "14:00"
prog3_time_end: "18:00"

# Programs 4-6 can be configured similarly
```

**How It Works:**
1. During configuration, optionally configure time-based programs in addition to or instead of single target entity
2. When `calculate_charge_soc` service runs, it checks the current time against all configured programs
3. If a matching time window is found, the corresponding program SOC entity is updated
4. If no program matches, it falls back to the single `target_soc_entity` (if configured)
5. Time windows can cross midnight (e.g., 22:00 to 06:00)

**Entity Naming Patterns:**

Solarman integration typically creates entities like:
- `number.deye_hybrid_prog1_capacity` (SOC target for slot 1)
- `number.deye_hybrid_prog2_capacity` (SOC target for slot 2)
- `time.deye_hybrid_prog1_time` (Start time for slot 1)
- etc.

Check your Solarman integration entities for the exact naming pattern.

**Migration from Single Entity:**

Existing configurations using `target_soc_entity` will continue to work without changes. To migrate:
1. Go to Integrations → Energy Optimizer → Configure
2. Navigate to the Time Programs step
3. Configure your desired program entities and time windows
4. Optionally clear `target_soc_entity` if you only want program-based control

## Services

### `energy_optimizer.calculate_charge_soc`

Calculate optimal battery charge target based on current conditions.

**Parameters:**
- `hours` (optional): Hours to cover with charge (default: 12)
- `force_charge` (optional): Force charging regardless of price (default: false)

**Example:**
```yaml
service: energy_optimizer.calculate_charge_soc
data:
  hours: 12
  force_charge: false
```

### `energy_optimizer.calculate_sell_energy`

Calculate sellable battery surplus based on price favorability.

**Parameters:**
- `min_profit_margin` (optional): Minimum price premium required (default: 20%)
- `auto_set_work_mode` (optional): Automatically switch to sell mode (default: false)

**Example:**
```yaml
service: energy_optimizer.calculate_sell_energy
data:
  min_profit_margin: 20
  auto_set_work_mode: true
```

### `energy_optimizer.estimate_heat_pump_usage`

Forecast daily heat pump consumption based on weather.

**Parameters:**
- `date` (optional): Date to estimate (default: today)

**Example:**
```yaml
service: energy_optimizer.estimate_heat_pump_usage
data:
  date: "2024-12-21"
```

### `energy_optimizer.optimize_battery_schedule`

Generate optimal daily battery charge/discharge schedule.

**Parameters:**
- `date` (optional): Date to optimize (default: tomorrow)
- `optimization_goal` (optional): Strategy - "cost_minimize", "self_consumption", "balanced" (default: "balanced")

**Example:**
```yaml
service: energy_optimizer.optimize_battery_schedule
data:
  date: "2024-12-21"
  optimization_goal: "cost_minimize"
```

## Sensors

| Sensor | Description | Unit |
|--------|-------------|------|
| `battery_reserve` | Energy above minimum SOC | kWh |
| `battery_space` | Space available for charging | kWh |
| `battery_capacity` | Total battery capacity | kWh |
| `usable_capacity` | Usable capacity (between min/max SOC) | kWh |
| `required_energy_morning` | Energy needed until noon | kWh |
| `required_energy_afternoon` | Energy needed 12:00-18:00 | kWh |
| `required_energy_evening` | Energy needed 18:00-22:00 | kWh |
| `surplus_energy` | Available surplus above requirements | kWh |
| `heat_pump_estimation` | Daily heat pump consumption forecast | kWh |

## Automation Examples

### Morning Grid Charging

```yaml
automation:
  - alias: "Energy: Morning Cheap Charging"
    trigger:
      - platform: state
        entity_id: binary_sensor.rce_pse_today_cheapest_window_active
        to: "on"
    condition:
      - condition: numeric_state
        entity_id: sensor.energy_optimizer_battery_soc
        below: 80
    action:
      - service: energy_optimizer.calculate_charge_soc
        data:
          hours: 12
          force_charge: true
```

### Evening Grid Selling

```yaml
automation:
  - alias: "Energy: Evening Expensive Selling"
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

## Troubleshooting

### Integration Not Loading
- Check Home Assistant logs for errors
- Verify all required entities exist and are accessible
- Ensure Home Assistant version is 2024.1.0 or later

### Sensors Show "Unavailable"
- Verify source sensor entities are available
- Check that battery SOC sensor provides numeric values
- Review configuration in Settings → Integrations → Energy Optimizer

### Services Not Working
- Ensure target SOC entity is writable (number domain)
- Check that price sensors provide numeric states
- Verify service parameters are within valid ranges

### Calculation Issues
- Review battery parameters (capacity, voltage, efficiency)
- Check SOC limits (min < max)
- Ensure price sensors provide consistent units

## Migration from YAML

See [MIGRATION.md](docs/MIGRATION.md) for detailed migration guide from YAML-based automations.

## Development

### Running Tests

```bash
pytest tests/
```

### Code Quality

```bash
# Format code
black custom_components/energy_optimizer/

# Lint
pylint custom_components/energy_optimizer/
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) file for details

## Credits

- **Author**: [@plebann](https://github.com/plebann)
- **Inspired by**: YAML-based energy optimization automations
- **Dependencies**: Home Assistant Core, ha-rce-pse, ha-solarman, Solcast Solar

## Support

- **Issues**: [GitHub Issues](https://github.com/plebann/EnergyOptimizer/issues)
- **Documentation**: [GitHub Wiki](https://github.com/plebann/EnergyOptimizer/wiki)
- **Community**: [Home Assistant Community](https://community.home-assistant.io/)