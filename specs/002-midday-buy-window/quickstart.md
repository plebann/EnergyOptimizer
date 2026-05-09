# Quickstart: Rozszerzenie Sensorów Okna Najniższej Ceny Sprzedaży

## Goal

Add two derived Home Assistant text sensors that expose the cheapest 8-quarter-hour sell-price window between 08:00 and 16:00 for the current local day and for the next local day, with a `price` attribute representing the rounded average price of the selected window.

## Implementation Steps

1. Extend the pure calculation module under `custom_components/energy_optimizer/calculations/` so it:
   - accepts day-scoped hourly payloads for either `prices_today` or `prices_tomorrow`,
   - expands each hour into 4 quarter-hour slots with the same price,
   - filters the target local day and the 08:00-16:00 interval,
   - chooses the cheapest contiguous 8-slot window,
   - returns the selected window plus its average price,
   - returns no valid result when data is incomplete,
   - resolves ties by earliest start time.
2. Add or extend derived sensor entities under `custom_components/energy_optimizer/entities/sensors/` so the integration publishes:
   - the existing current-day midday sell window sensor backed by `prices_today`,
   - an analogous tomorrow midday sell window sensor backed by `prices_tomorrow`.
3. Ensure each sensor publishes state in `HH:MM-HH:MM` format, includes `price` only when available, and omits `price` when the sensor is `unavailable`.
4. Wire both sensors into `custom_components/energy_optimizer/sensor.py` and/or shared sensor registration so payload-source updates trigger recalculation through the existing refresh path.
5. Extend translations in `custom_components/energy_optimizer/translations/en.json` for both derived sensors.
6. Add focused tests for calculation behavior, day separation, `price`, and entity publication.

## Suggested File Touches

- `custom_components/energy_optimizer/calculations/price_windows.py`
- `custom_components/energy_optimizer/entities/sensors/pricing.py`
- `custom_components/energy_optimizer/entities/sensors/__init__.py`
- `custom_components/energy_optimizer/sensor.py`
- `custom_components/energy_optimizer/coordinator.py`
- `custom_components/energy_optimizer/translations/en.json`
- `tests/test_price_windows.py`
- `tests/test_pricing_sensors.py`

## Validation

Run focused tests first:

```bash
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/test_price_windows.py tests/test_pricing_sensors.py -q'
```

If day-separation logic is also covered in a broader time-window regression file, run the expanded focused set:

```bash
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/test_price_windows.py tests/test_pricing_sensors.py tests/test_time_windows.py -q'
```

## Manual Verification

1. Ensure the configured sell-price source exposes both `prices_today` and `prices_tomorrow` payloads.
2. Reload the integration.
3. Confirm the current-day sensor publishes a value like `12:00-14:00` and a `price` attribute when complete `prices_today` data exists.
4. Confirm the tomorrow sensor publishes its own value and `price` when complete `prices_tomorrow` data exists.
5. Remove or corrupt one required hourly input for only one day and confirm only the corresponding sensor becomes `unavailable` and omits `price`.
6. Change only the buy-price input and confirm neither derived sell-window sensor changes.