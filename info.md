# Energy Optimizer

Intelligent battery charging and energy optimization for Home Assistant.

## Features

- 🔋 Smart battery scheduling with overnight and morning routines
- ☀️ PV forecast integration for intelligent charging decisions
- 📊 Comprehensive energy monitoring sensors
- 🔧 Flexible entity-based configuration

## Quick Start

1. Install recommended integrations:
   - **ha-rce-pse**: Electricity pricing data
   - **ha-solarman**: Battery and inverter control
   - **Solcast Solar**: PV forecasting (optional)

2. Add Energy Optimizer integration via Settings → Integrations

3. Follow the configuration wizard to select your entities

4. Create automations using the provided services and sensors

## Services

- `morning_grid_charge`: Size and set Program 2 SOC for the morning window when reserve is insufficient
- `overnight_schedule`: Generate daily optimization schedule

## Documentation

Full documentation available at: https://github.com/plebann/EnergyOptimizer

## Support

Report issues at: https://github.com/plebann/EnergyOptimizer/issues
