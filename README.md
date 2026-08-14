# Energy Optimizer for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/plebann/EnergyOptimizer.svg)](https://github.com/plebann/EnergyOptimizer/releases)

Energy Optimizer is a Home Assistant custom integration focused on price-aware battery optimization with programmable SOC targets.

## What It Does

- Overnight handling: runs nightly at 22:00 and selects a mode based on PV forecast, balancing cadence, and battery state.
- Morning grid charge: plans a morning top-up to cover high-tariff demand when needed.
- Afternoon grid charge: plans an afternoon top-up to cover evening demand and optional arbitrage.
- Arbitrage gates use a minimum **margin** (`sell_price - buy_reference_price`), not a raw sell-price floor.
- Consistent decision logging with sensors and notifications.

## Behavior Notes

- Notifications: decision outcomes are logged and can trigger notifications.
- Data sources: services rely on current Home Assistant states; ensure numeric sensors return valid values.

## What’s Included

- Platforms: Sensor, Binary Sensor.
- Services: morning_grid_charge, afternoon_grid_charge, overnight_schedule.
- Sensors: battery, configuration, tracking, forecast helpers, and pricing window sensors.
- Pricing sensors include buy-window references used by arbitrage decisions, including `morning_sell_buy_reference`.

### Midday Sell Window Sensors

The integration publishes two derived midday sell-window sensors:

- **Current day**: `sensor.<device>_midday_sell_window`
- **Tomorrow**: `sensor.<device>_midday_sell_window_tomorrow`

Both sensors publish the cheapest 8-quarter-hour (2-hour) sell-price window between 08:00 and 16:00 for their respective local day.

- **Format**: `HH:MM-HH:MM` (e.g., `12:00-14:00`)
- **Attribute**: `price` with the rounded average sell price for the selected window in PLN/kWh
- **Source**: Reads hourly `prices_today` and `prices_tomorrow` data for the configured sell-price entity from shared coordinator state and expands each hour into 4 quarter-hours during selection
- **Unavailable**: The affected sensor becomes unavailable when there is insufficient data to form a full 8-slot window, and `price` is omitted in that state
- **Tie-break**: When multiple windows share the same total cost, the earliest window is selected
- **Isolation**: Ignores buy-price-only changes and keeps current-day and tomorrow payload updates isolated from each other
- **Update**: Recalculates automatically whenever the sell-price entity payload changes through the normal coordinator refresh path

## Configuration (UI-Only)

- Mandatory: price sensor, average price sensor, battery SOC sensor, battery power sensor, battery capacity/voltage/efficiency, min/max SOC, and at least one program SOC entity with a start-time entity.
- Optional: program SOCs 2-6 with start times, PV forecast sensors, daily or windowed load sensors, work mode/charge/discharge/grid charge entities, heat pump toggle plus temperature/power sensors, balancing interval and PV threshold, and optional max charge current entity for balancing.
- Options flow: adjust battery parameters, efficiency, balancing interval/PV threshold, max charge current entity, and load-window sensors after setup.

### Service Architecture

Service handlers live in `custom_components/energy_optimizer/service_handlers/`:
- `morning.py` - Morning grid charge
- `afternoon.py` - Afternoon grid charge (short planning path with arbitrage support)
- `overnight.py` - Overnight handling

### Sensor Platform

Base sensor class with coordinator integration:
- Battery monitoring sensors (reserve, space, capacity)
- Energy balance sensors (required energy, surplus)
- Heat pump estimation sensor
- Optimization tracking sensors (last balancing, history)

### Optimization History Format

`sensor.<device>_optimization_history` retains compact decision records for up to
14 days. The sensor also enforces a 14 KiB attribute budget, removing the oldest
records when necessary. Full diagnostics for the most recent decision remain in
the Last Optimization sensor.

Each history record uses these compact keys:

| Key | Meaning |
| --- | --- |
| `t` | Decision timestamp in local ISO 8601 format |
| `s` | Scenario: `mc` morning charge, `ac` afternoon charge, `ms` morning sell, `es` evening sell |
| `a` | Action: `c` charge, `s` sell, `n` no action, `r` sell restore |
| `r` | Compact decision reason (`arb` arbitrage, `pv` PV sufficiency, `db` day-buy boundary, `sf` static fallback, `sun` sunset, `n` normal) |
| `v` | Applied values: `s` target SOC, `c` charge current, `e` export power |
| `m` | Metrics: `g` charge gap, `x` sell surplus, `q` required energy, `p` sell price, `b` arbitrage buy price, `m` arbitrage margin |
| `w` | Final decision horizons, each as `[purpose, start_hour, start_kind, end_hour, end_kind, ends_tomorrow]` |

The current purpose codes are `cr` (charge reserve) and `sr` (sell reserve).
Boundary codes are `nb_e` (night buy end), `db_s` (day buy start), `db_e`
(day buy end), `nb_t_s` (tomorrow night buy start), `next_h` (next full hour),
`day_e` (end of the current day), `pv_s` (PV sufficiency), `arb_b` (arbitrage buy hour), `tariff_e` (tariff end),
`sw_e` (sell window end), and `sunset` (sunset).

Last Optimization includes sell-target diagnostics when a sell decision is made:
`rt` is the target SOC before the minimum-SOC safeguard, `rg` is the additional
SOC reserved for required energy after discharge-efficiency compensation, and
`ra` indicates whether that reserve was applied.

### Decision replay logs

For reproducible decision diagnostics, the integration emits JSON lines through
the `custom_components.energy_optimizer.decision_replay` logger:

- `ENERGY_OPTIMIZER_CONFIG_SNAPSHOT v1` is emitted once for each configuration
  revision. It contains decision settings and semantic aliases for configured
  entities.
- `ENERGY_OPTIMIZER_DECISION_REPLAY v1` is emitted for each completed decision.
  It references the configuration snapshot and contains only dynamic inputs
  read by the decision, its time/trigger, source revision, and expected result.

Configure that logger in the host/container logging setup to route it to a
dedicated rotating file. The integration does not create or manage log files
itself.

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
- **Testability**: 81 unit tests covering edge cases and calculations
- **Extensibility**: Easy to add new services and sensors

## Installation

- HACS: add the repository as a custom integration and install.
- Manual: copy custom_components/energy_optimizer into your Home Assistant config and restart.

## Support

- Issues and requests: GitHub Issues.
- Updates: GitHub Releases.

## License

- MIT License (see LICENSE).