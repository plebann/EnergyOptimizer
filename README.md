# Energy Optimizer for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/plebann/EnergyOptimizer.svg)](https://github.com/plebann/EnergyOptimizer/releases)

Energy Optimizer is a Home Assistant custom integration focused on price-aware battery optimization with programmable SOC targets.

## What It Does

- Overnight handling: runs nightly at 22:00 (manual calls behave the same) and picks one of three modes using PV forecast, balancing cadence, and battery space:
   - Battery Balancing: if balancing is due and tomorrow's PV forecast is below the balancing PV threshold, set program SOCs 1/2/6 to max SOC and optional max charge current to 23 A.
   - Battery Preservation: if PV forecast × 0.9 is lower than available battery space, lock program SOC 1 and 6 to the current SOC (bounded by min SOC) to avoid inefficient cycling. Program 2 is intentionally untouched here because a separate 04:00 optimization will manage it.
   - Normal Operation: if previously locked and conditions improve, restore program SOCs 1/2/6 to min SOC.
   - If none of the above match, no changes are made.
   - PV forecast compensation sensor is refreshed here (today → yesterday, update today values, recalc factor).
   - Balancing completion is stamped only after SOC stays ≥97% for 2 hours; schedule `check_and_update_balancing_completion` periodically (e.g., every 5 minutes) to advance the timestamp.
- Balancing completion check: every 5 minutes, stamps last balancing when SOC stays ≥97% for 2 hours.
- Morning grid charge: at 04:00 (trigger via automation), if Program 2 SOC < 100% and battery reserve is below required morning energy (06:00-13:00), set Program 2 SOC to cover the deficit using windowed load sensors and daily losses.
- Afternoon grid charge: after tariff end, size Program 2 SOC to cover evening demand and optional arbitrage window.

## Behavior Notes

- Notifications: overnight_schedule sends notify messages when modes change. The service is parameterless.
- Data sources: services rely on current Home Assistant states; ensure numeric sensors return valid values.

## What’s Included

- Platforms: Sensor only.
- Services: morning_grid_charge, afternoon_grid_charge, overnight_schedule.
- Sensors:
  - Battery: battery_reserve, battery_space, battery_capacity, usable_capacity
  - Config values: battery_capacity_ah, battery_voltage_config, battery_efficiency_config, min_soc_config, max_soc_config
   - Tracking: last_balancing_timestamp, last_optimization, optimization_history
   - Forecast: pv_forecast_compensation

## Configuration (UI-Only)

- Mandatory: price sensor, average price sensor, battery SOC sensor, battery power sensor, battery capacity/voltage/efficiency, min/max SOC, and at least one program SOC entity with a start-time entity.
- Optional: program SOCs 2-6 with start times, PV forecast sensors, daily or windowed load sensors, work mode/charge/discharge/grid charge entities, heat pump toggle plus temperature/power sensors, balancing interval and PV threshold, and optional max charge current entity for balancing.
- Options flow: adjust battery parameters, efficiency, balancing interval/PV threshold, max charge current entity, and load-window sensors after setup.

### Service Architecture

Service handlers live in `custom_components/energy_optimizer/service_handlers/`:
- `morning.py` - Morning grid charge sizing and Program 2 SOC adjustment
- `overnight.py` - Battery schedule optimization (balancing/preservation/normal at 22:00)

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

### Key Design Principles

- **Separation of Concerns**: Service handlers, helpers, and calculations in dedicated modules
- **HACS Compliance**: Follows Home Assistant Custom Component best practices
- **Maintainability**: Small, focused modules (~90-600 lines each)
- **Testability**: 48 unit tests covering edge cases and calculations
- **Extensibility**: Easy to add new services and sensors

## Installation

- HACS: add the repository as a custom integration and install.
- Manual: copy custom_components/energy_optimizer into your Home Assistant config and restart.

## Support

- Issues and requests: GitHub Issues.
- Updates: GitHub Releases.

## License

- MIT License (see LICENSE).