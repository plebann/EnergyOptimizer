# Implementation Plan: Rozszerzenie Sensorów Okna Najniższej Ceny Zakupu

**Branch**: `[002-midday-buy-window]` | **Date**: 2026-05-31 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-midday-buy-window/spec.md`

## Summary

Extend the existing midday buy-window feature so the integration publishes two day-scoped Home Assistant sensors derived only from buy-price payloads: one for today and one for tomorrow. Both sensors publish the selected window in `HH:MM-HH:MM` format plus a rounded `price` attribute, the today sensor additionally publishes `is_active`, and the selection logic gives priority to the full span from the first to the last zero or quasi-zero buy price before falling back to the existing cheapest 8-quarter-hour midday window with earliest-start tie-breaking.

## Technical Context

**Language/Version**: Python in the Home Assistant custom integration runtime  
**Primary Dependencies**: Home Assistant config entries, `DataUpdateCoordinator`, `CoordinatorEntity`/`SensorEntity`, existing Energy Optimizer entity bases and translations, pytest  
**Storage**: N/A for feature-specific persistence; all outputs are derived from coordinator-managed price payload snapshots  
**Testing**: `pytest` with focused unit and entity tests under `tests/`  
**Target Platform**: Home Assistant custom integration distributed via HACS  
**Project Type**: Single-project Home Assistant custom integration  
**Performance Goals**: Recompute both midday buy-window sensors inside the existing refresh/listener path with negligible overhead by scanning at most two hourly buy-price payloads already held in memory  
**Constraints**: UI-only configuration; no blocking I/O; no new external APIs; buy-price data only; today sensor uses `prices_today`; tomorrow sensor uses `prices_tomorrow`; each hourly input is treated as four quarter-hours with the same value; the evaluated range stays inside `08:00-16:00` local time; standard windows remain 8 quarter-hours long; zero or `< 0.05 PLN/kWh` prices are treated as quasi-zero and take precedence; state format is `HH:MM-HH:MM`; `price` is a float rounded to 2 decimals; `is_active` is published only for the today sensor; unavailable sensors omit dependent attributes; translation-backed naming and stable config-entry-scoped unique IDs must be preserved  
**Scale/Scope**: Two derived midday buy-window sensors, one shared calculation path, one buy-window output contract, translation updates, and targeted tests for quasi-zero precedence, today/tomorrow separation, `price`, `is_active`, and `unavailable` behavior

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **HA-first scope**: PASS before design. The feature remains a read-only Home Assistant output derived from already-configured HA entities.
- **Module separation**: PASS before design. Window-selection rules stay in the calculation layer while entity publication and registration stay in HA-facing sensor files.
- **Controlled degradation**: PASS before design. The spec requires `unavailable` for any day that cannot produce a trustworthy result and omits dependent attributes in that state.
- **Naming and registry stability**: PASS before design. The design keeps translation-backed names, `_attr_has_entity_name = True`, and stable config-entry-based unique IDs.
- **Testing and observability**: PASS before design. The feature increases observability through `price` and `is_active` and requires deterministic tests for both algorithmic and entity behavior.

### Post-Design Re-check

- **HA-first scope**: PASS after design. `research.md`, `data-model.md`, and the contract keep the feature inside additive HA-derived sensor publication using coordinator state as the only source.
- **Module separation**: PASS after design. The design centralizes buy-window selection in `custom_components/energy_optimizer/calculations/price_windows.py` while keeping `pricing.py` thin and declarative.
- **Controlled degradation**: PASS after design. The design requires `unavailable` on incomplete or invalid data, isolates today/tomorrow payloads, and omits `price` and `is_active` whenever no valid window is available.
- **Naming and registry stability**: PASS after design. The design keeps the existing today sensor identity, adds the tomorrow counterpart, and preserves translation-backed metadata.
- **Testing and observability**: PASS after design. The design requires explicit tests for quasi-zero precedence, earliest-start fallback, day separation, `is_active`, and attribute omission.

## Project Structure

### Documentation (this feature)

```text
specs/002-midday-buy-window/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── midday-buy-window-sensor.md
└── tasks.md
```

### Source Code (repository root)

```text
custom_components/energy_optimizer/
├── calculations/
│   └── price_windows.py
├── coordinator.py
├── entities/
│   └── sensors/
│       ├── __init__.py
│       └── pricing.py
├── sensor.py
└── translations/
    └── en.json

tests/
├── test_price_windows.py
├── test_pricing_sensors.py
└── test_helpers.py
```

**Structure Decision**: Keep the feature inside the existing `energy_optimizer` integration. Reuse coordinator-managed buy-price payload snapshots, keep the business rules in `custom_components/energy_optimizer/calculations/price_windows.py`, publish the today/tomorrow midday buy-window sensors from `custom_components/energy_optimizer/entities/sensors/pricing.py`, wire them additively through `custom_components/energy_optimizer/sensor.py`, extend translations in `custom_components/energy_optimizer/translations/en.json`, and validate the behavior with focused calculation and entity tests that cover quasi-zero span selection, standard fallback selection, today/tomorrow isolation, and attribute publication.

## Complexity Tracking

No constitution violations identified. The feature fits the current single-integration architecture without requiring exceptions.
