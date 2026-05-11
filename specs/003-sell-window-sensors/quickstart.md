# Quickstart: Cztery Sensory Optymalnych Okien Sprzedazy Energii

## Goal

Add four derived Home Assistant sensors alongside the current pricing sensor set that publish the best one-hour sell window start time for today morning, today evening, tomorrow morning, and tomorrow evening, plus ranked comparison attributes for the second-best candidate.

## Implementation Steps

1. Refactor `custom_components/energy_optimizer/calculations/price_windows.py` so it:
   - consumes hourly `prices_today` and `prices_tomorrow` records directly,
   - filters candidates by business day and by one of two ranges: morning `04:00-10:00` or evening `16:00-22:00`,
   - treats each full hour as one candidate window,
   - ranks candidates by price descending and start time ascending,
   - returns the best and second-best candidates plus an optional percentage gap.
2. Add four ranked sensor variants in `custom_components/energy_optimizer/entities/sensors/pricing.py` while leaving the current midday and other pricing sensor classes unchanged:
   - today morning,
   - today evening,
   - tomorrow morning,
   - tomorrow evening.
3. Update the HA-facing output contract so each ranked sensor:
   - publishes `HH:MM` as the state,
   - publishes `price`, `second_window_start`, and `second_window_price` when available,
   - publishes `second_window_gap_pct` only when the best price is non-zero,
   - becomes `unavailable` when fewer than two valid hourly candidates exist for its slice.
4. Update `custom_components/energy_optimizer/entities/sensors/__init__.py` and `custom_components/energy_optimizer/sensor.py` so the new four sensor classes are registered while the old midday pair remains in the active sensor list.
5. Extend `custom_components/energy_optimizer/translations/en.json` with translation keys for the four ranked sensors and their revised semantics.
6. Add or update focused tests in `tests/test_price_windows.py` and `tests/test_pricing_sensors.py` for ranking, tie-breaks, attribute rounding, zero-best-price percentage omission, `unavailable` behavior, and coexistence with existing sensors.

## Suggested File Touches

- `custom_components/energy_optimizer/calculations/price_windows.py`
- `custom_components/energy_optimizer/entities/sensors/pricing.py`
- `custom_components/energy_optimizer/entities/sensors/__init__.py`
- `custom_components/energy_optimizer/sensor.py`
- `custom_components/energy_optimizer/translations/en.json`
- `tests/test_price_windows.py`
- `tests/test_pricing_sensors.py`

## Validation

Run the focused pricing tests first:

```bash
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/test_price_windows.py tests/test_pricing_sensors.py -q'
```

If sensor registration coverage also moves, rerun a slightly broader slice:

```bash
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/test_price_windows.py tests/test_pricing_sensors.py tests/test_services_registration.py -q'
```

## Manual Verification

1. Ensure the configured sell-price source exposes hourly `prices_today` and `prices_tomorrow` payloads with `time` and `price` fields.
2. Reload the integration.
3. Confirm the four ranked sensors appear with distinct names for today/tomorrow and morning/evening while the existing sensors remain present.
4. Confirm each available sensor publishes `HH:MM` as state and rounded `price`, `second_window_start`, and `second_window_price` attributes.
5. Confirm `second_window_gap_pct` is shown with one decimal place when the best price is non-zero and omitted when the best price is zero.
6. Remove one required hourly record from a single day/range and confirm only the affected sensor becomes `unavailable`.
7. Change only the buy-price input and confirm none of the ranked sell-window sensors change.
8. Confirm existing midday and other pricing sensors keep their prior state format and remain available after the new sensors are added.