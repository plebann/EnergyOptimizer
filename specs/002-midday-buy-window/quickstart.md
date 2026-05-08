# Quickstart: Okno Najniższej Ceny Sprzedaży w Środku Dnia

## Goal

Add a derived Home Assistant text sensor that exposes the cheapest 8-quarter-hour sell-price window between 08:00 and 16:00 for the current local day, calculated from hourly input expanded into quarter-hours.

## Implementation Steps

1. Add a pure calculation module under `custom_components/energy_optimizer/calculations/` that:
   - reads the configured current-day hourly price-series payload,
   - expands each hour into 4 quarter-hour slots with the same price,
   - filters the current local day and the 08:00-16:00 interval,
   - chooses the cheapest contiguous 8-slot window,
   - returns no result when data is incomplete,
   - resolves ties by earliest start time.
2. Add a dedicated text sensor under `custom_components/energy_optimizer/entities/sensors/` with a translation key and stable unique ID.
3. Wire the new sensor into `custom_components/energy_optimizer/sensor.py` and ensure price-source updates trigger recalculation through the existing refresh path.
4. Update translations in `custom_components/energy_optimizer/translations/en.json`.
5. Add focused tests for both the pure calculation logic and the published entity state.

## Suggested File Touches

- `custom_components/energy_optimizer/calculations/price_windows.py`
- `custom_components/energy_optimizer/entities/sensors/pricing.py`
- `custom_components/energy_optimizer/entities/sensors/__init__.py`
- `custom_components/energy_optimizer/sensor.py`
- `custom_components/energy_optimizer/coordinator.py` or the new calculation module, depending on where raw attribute access is centralized
- `custom_components/energy_optimizer/translations/en.json`
- `tests/test_price_windows.py`
- `tests/test_pricing_sensors.py`

## Validation

Run focused tests first:

```bash
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/test_pricing_sensors.py tests/test_time_windows.py -q'
```

If the pure algorithm ends up in a dedicated file with its own tests, run the narrower set:

```bash
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/test_price_windows.py tests/test_pricing_sensors.py -q'
```

## Manual Verification

1. Ensure the configured price-series entity exposes current-day hourly sell prices.
2. Reload the integration.
3. Confirm the new sensor publishes a value like `12:00-14:00` when complete data exists.
4. Remove or corrupt one required hourly input or one expanded quarter-hour candidate path and confirm the sensor becomes `unavailable`.
5. Change only the buy-price input and confirm the window sensor does not change.
