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

## Architecture

Energy Optimizer follows Home Assistant best practices with a modular, maintainable architecture:

### Module Structure

```
custom_components/energy_optimizer/
├── __init__.py          # Integration setup (90 lines)
├── config_flow.py       # Configuration UI
├── const.py             # Constants and defaults
├── manifest.json        # Integration metadata
├── sensor.py            # Sensor platform (676 lines)
├── services.yaml        # Service definitions
├── strings.json         # UI translations
├── helpers.py           # Utility functions (135 lines)
├── services.py          # Service handlers (600 lines)
├── coordinator.py       # Data coordinator scaffolding
└── calculations/        # Calculation modules
    ├── battery.py       # Battery calculations
    ├── charging.py      # Charging logic
    ├── energy.py        # Energy balance
    ├── heat_pump.py     # Heat pump estimations
    └── utils.py         # Math utilities
```

### Key Design Principles

- **Separation of Concerns**: Service handlers, helpers, and calculations in dedicated modules
- **HACS Compliance**: Follows Home Assistant Custom Component best practices
- **Maintainability**: Small, focused modules (~90-600 lines each)
- **Testability**: 48 unit tests covering edge cases and calculations
- **Extensibility**: Easy to add new services and sensors

### Service Architecture

All service handlers are in `services.py`:
- `handle_calculate_charge_soc` - Battery charging optimization
- `handle_calculate_sell_energy` - Surplus energy calculation
- `handle_estimate_heat_pump` - Heat pump consumption estimation
- `handle_optimize_schedule` - Battery schedule optimization (3 scenarios)

### Sensor Platform

Base sensor class with coordinator integration:
- Battery monitoring sensors (reserve, space, capacity)
- Energy balance sensors (required energy, surplus)
- Heat pump estimation sensor
- Optimization tracking sensors (last balancing, history)

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

# Energy Optimizer for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/plebann/EnergyOptimizer.svg)](https://github.com/plebann/EnergyOptimizer/releases)

Energy Optimizer is a Home Assistant custom integration focused on price-aware battery optimization with programmable SOC targets.

## What It Does

- Price-aware charging: compares current price to average, sizes required energy, and writes targets to the active program SOC entity.
- Overnight handling: runs nightly at 22:00 to choose one of three modes based on PV forecast and balancing interval:
  - Battery Balancing (push to 100% and max charge current when due and PV is low)
  - Battery Preservation (lock at current/min SOC when PV is insufficient for the available space)
  - Normal Operation (restore program SOCs to minimum when conditions improve)
- Balancing completion check: every 5 minutes, stamps last balancing when SOC stays ≥97% for 2 hours.
- Optional heat pump estimate logging when enabled and a temperature sensor is provided.

## What’s Included

- Platforms: Sensor only.
- Services: calculate_charge_soc, calculate_sell_energy, estimate_heat_pump_usage, overnight_schedule.
- Sensors:
  - Battery: battery_reserve, battery_space, battery_capacity, usable_capacity
  - Config values: battery_capacity_ah, battery_voltage_config, battery_efficiency_config, min_soc_config, max_soc_config
  - Tracking: last_balancing_timestamp, last_optimization, optimization_history

## Configuration (UI-Only)

- Mandatory: price sensor, average price sensor, battery SOC sensor, battery power sensor, battery capacity/voltage/efficiency, min/max SOC, and at least one program SOC entity with a start-time entity.
- Optional: program SOCs 2-6 with start times, PV forecast sensors, daily or windowed load sensors, work mode/charge/discharge/grid charge entities, heat pump toggle plus temperature/power sensors, balancing interval and PV threshold.
- Options flow: adjust battery parameters, efficiency, balancing interval, and load-window sensors after setup.

## Behavior Notes

- Targeting: calculate_charge_soc only writes to the active program SOC entity selected by configured start times; there is no single target SOC fallback.
- Notifications: overnight_schedule sends notify messages when modes change.
- Data sources: services rely on current Home Assistant states; ensure numeric sensors return valid values.

## Installation

- HACS: add the repository as a custom integration and install.
- Manual: copy custom_components/energy_optimizer into your Home Assistant config and restart.

## Support

- Issues and requests: GitHub Issues.
- Updates: GitHub Releases.

## License

- MIT License (see LICENSE).