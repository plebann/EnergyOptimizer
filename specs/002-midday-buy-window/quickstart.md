# Quickstart: Rozszerzenie Sensorów Okna Najniższej Ceny Zakupu

## Goal

Add two derived Home Assistant sensors that expose the selected midday buy window between `08:00` and `16:00` for today and tomorrow, publish the average selected price as `price`, and publish `is_active` only for the today sensor.

## Implementation Steps

1. Extend `custom_components/energy_optimizer/calculations/price_windows.py` so it:
   - consumes hourly buy-price payloads from `prices_today` and `prices_tomorrow`,
   - filters records to the evaluated local day,
   - expands each full hour into four quarter-hour slots with the same price semantics,
   - gives priority to the full span from the first to the last buy-price entry below `0.05 PLN/kWh`,
   - falls back to the cheapest contiguous 8-quarter-hour midday window when no quasi-zero entries exist,
   - resolves standard-window ties by earliest start,
   - returns no result when a valid day-scoped window cannot be proven.
2. Extend `custom_components/energy_optimizer/entities/sensors/pricing.py` so the integration publishes:
   - the existing today midday buy-window sensor backed by `prices_today`, with `price` and `is_active`,
   - the tomorrow midday buy-window sensor backed by `prices_tomorrow`, with `price` and without `is_active`.
3. Ensure each sensor publishes state in `HH:MM-HH:MM` format, omits dependent attributes when unavailable, and keeps the tomorrow sensor free of `is_active` even when it has a valid result.
4. Wire both sensors through the existing registration and coordinator refresh path in `custom_components/energy_optimizer/sensor.py` and shared entity exports.
5. Extend translation keys in `custom_components/energy_optimizer/translations/en.json` for `midday_buy_window` and `midday_buy_window_tomorrow`.
6. Add focused tests for quasi-zero precedence, standard fallback, today/tomorrow separation, `price`, `is_active`, and unavailable-state attribute omission.

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

Run focused feature tests first:

```bash
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/test_price_windows.py tests/test_pricing_sensors.py -q'
```

If helper or supporting payload behavior also moved, rerun the expanded focused set:

```bash
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/test_price_windows.py tests/test_pricing_sensors.py tests/test_helpers.py -q'
```

## Manual Verification

1. Ensure the configured buy-price source exposes both `prices_today` and `prices_tomorrow` payloads.
2. Reload the integration.
3. Confirm the today sensor publishes a value like `10:00-12:00`, a rounded `price`, and `is_active` set to `on` or `off` when complete `prices_today` data exists.
4. Confirm the tomorrow sensor publishes its own `HH:MM-HH:MM` value and rounded `price` when complete `prices_tomorrow` data exists.
5. Confirm the tomorrow sensor does **not** publish `is_active` even when it has a valid window.
6. Introduce at least one buy-price entry below `0.05 PLN/kWh` and confirm the published window expands to the full span from the first to the last such occurrence in that day.
7. Remove or corrupt one required hourly input for only one day and confirm only the corresponding sensor becomes `unavailable` and omits dependent attributes.
8. Use a current local time inside the published today window and confirm `is_active == on`; move outside the window and confirm `is_active == off`.
9. Change only the sell-price input and confirm neither midday buy-window sensor changes.
