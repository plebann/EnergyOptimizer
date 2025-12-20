# Energy Optimizer

Intelligent battery charging and energy optimization for Home Assistant.

## Features

- 🔋 Smart battery charge/discharge scheduling based on electricity prices
- 💰 Cost optimization with price-based decision making
- ☀️ PV forecast integration for intelligent charging
- 🌡️ Heat pump consumption estimation
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

- `calculate_charge_soc`: Calculate optimal charge target
- `calculate_sell_energy`: Determine sellable surplus
- `estimate_heat_pump_usage`: Forecast heat pump consumption
- `optimize_battery_schedule`: Generate daily optimization schedule

## Documentation

Full documentation available at: https://github.com/plebann/EnergyOptimizer

## Support

Report issues at: https://github.com/plebann/EnergyOptimizer/issues
