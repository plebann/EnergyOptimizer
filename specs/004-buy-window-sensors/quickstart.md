# Quickstart: Cztery Sensory Optymalnych Okien Zakupu Energii

## Goal

Add four derived Home Assistant sensors alongside the current pricing sensor set that publish the best two-hour buy-window start time for today night, today day, tomorrow night, and tomorrow day, plus the selected average price and negative-price flag.

## Implementation Steps

1. Extend `custom_components/energy_optimizer/calculations/price_windows.py` so it:
   - consumes hourly `prices_today` and `prices_tomorrow` buy-price records directly,
   - filters entries by business day,
   - forms contiguous two-hour candidates starting only on full hours,
   - evaluates candidates inside either the night range `00:00-06:00` or the day range `10:00-18:00`,
   - ranks candidates by average buy price ascending with the clarified night/day tie-break policies,
   - returns one selected candidate with raw average price and enough information for HA publication.
2. Add four buy-window sensor variants in `custom_components/energy_optimizer/entities/sensors/pricing.py` while leaving the current sell-window, midday sell-window, and other pricing sensor classes unchanged:
   - today night,
   - today day,
   - tomorrow night,
   - tomorrow day.
3. Update the HA-facing output contract so each buy-window sensor:
   - publishes `HH:MM` as the state,
   - publishes `price` rounded to 3 decimals when available,
   - publishes `is_negative` as a boolean when available,
   - becomes `unavailable` when no full valid two-hour candidate exists for its slice,
   - keeps tomorrow sensors `unavailable` when `prices_tomorrow` is an empty list.
4. Update `custom_components/energy_optimizer/entities/sensors/__init__.py` and `custom_components/energy_optimizer/sensor.py` so the new four sensor classes are registered additively while the existing pricing sensor list remains intact.
5. Extend `custom_components/energy_optimizer/translations/en.json` with translation keys for the four buy-window sensors.
6. Add or update focused tests in `tests/test_price_windows.py` and `tests/test_pricing_sensors.py` for candidate building, tie-breaks, empty tomorrow payload handling, attribute publication, negative-price behavior, and `unavailable` semantics.

## Suggested File Touches

- `custom_components/energy_optimizer/calculations/price_windows.py`
- `custom_components/energy_optimizer/entities/sensors/pricing.py`
- `custom_components/energy_optimizer/entities/sensors/__init__.py`
- `custom_components/energy_optimizer/sensor.py`
- `custom_components/energy_optimizer/translations/en.json`
- `tests/test_price_windows.py`
- `tests/test_pricing_sensors.py`
- `tests/test_services_registration.py`

## Validation

Run the focused pricing tests first:

```bash
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/test_price_windows.py tests/test_pricing_sensors.py -q'
```

If sensor registration coverage also moves, rerun the broader pricing slice:

```bash
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/test_price_windows.py tests/test_pricing_sensors.py tests/test_services_registration.py -q'
```

## Manual Verification

1. Ensure the configured buy-price source exposes hourly `prices_today` and `prices_tomorrow` payloads with `time` and `price` fields.
2. Reload the integration.
3. Confirm the four buy-window sensors appear with distinct names for today/tomorrow and night/day while the existing pricing sensors remain present.
4. Confirm each available sensor publishes `HH:MM` as state plus rounded `price` and boolean `is_negative` attributes.
5. Confirm equal-price night ties pick the window ending closest to `06:00`.
6. Confirm equal-price day ties pick the window starting closest to `13:00`, and if still tied, the earlier start wins.
7. Clear `prices_tomorrow` to an empty list and confirm only the two tomorrow buy-window sensors become `unavailable`.
8. Remove one required hourly record from a single day/range and confirm only the affected sensor becomes `unavailable`.
9. Change only the sell-price input and confirm none of the buy-window sensors change.