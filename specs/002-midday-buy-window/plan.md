# Implementation Plan: Rozszerzenie Sensorów Okna Najniższej Ceny Sprzedaży

**Branch**: `[002-midday-buy-window]` | **Date**: 2026-05-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-midday-buy-window/spec.md`

## Summary

Extend the existing midday sell-window feature into a day-scoped sensor pair: keep the current-day text sensor for the cheapest sell-price window between 08:00 and 16:00, add a second analogous tomorrow sensor, and publish a rounded float `price` attribute for the average selected window price when available. The implementation will reuse one pure calculation path, read `prices_today` and `prices_tomorrow` from shared integration state, preserve earliest-start tie-breaking and `unavailable` semantics, omit `price` when a sensor is unavailable, and keep Home Assistant entity logic thin and translation-backed.

## Technical Context

**Language/Version**: Python in the Home Assistant custom integration runtime  
**Primary Dependencies**: Home Assistant config entries, `DataUpdateCoordinator`, `CoordinatorEntity`/`SensorEntity`, existing Energy Optimizer entity bases and translations, pytest  
**Storage**: N/A for feature-specific persistence; state is derived from shared Home Assistant entity state and attributes  
**Testing**: `pytest` with focused unit and entity tests under `tests/`  
**Target Platform**: Home Assistant custom integration distributed via HACS  
**Project Type**: Single-project Home Assistant custom integration  
**Performance Goals**: Recompute both day-scoped windows inside the existing refresh/listener path with negligible overhead by scanning at most two hourly payloads, expanding them in memory to quarter-hour slots, and reusing a single pure selector  
**Constraints**: UI-only configuration, no blocking I/O, no new external APIs, sell-price data only, `prices_today` for the current-day sensor, `prices_tomorrow` for the tomorrow sensor, hourly input expanded into 4 quarter-hours per hour, shared-state access instead of direct entity reads, earliest-window tie-break, `unavailable` on insufficient data, omit `price` on unavailable, translation-backed naming, stable unique IDs tied to the config entry  
**Scale/Scope**: Two derived sensors sharing one calculation core, one updated output contract, one translation update, and targeted tests for day separation, average-price publishing, and controlled degradation

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **HA-first scope**: PASS before design. The feature remains a derived Home Assistant output built from existing HA price entities.
- **Module separation**: PASS before design. The plan keeps window selection and averaging in a calculation module and leaves entity registration/publishing in HA-facing files.
- **Controlled degradation**: PASS before design. The clarified contract explicitly maps incomplete or invalid day-scoped data to `unavailable` and omits `price` in that state.
- **Naming and registry stability**: PASS before design. Both derived sensors will use translation-backed naming, `_attr_has_entity_name = True`, and stable config-entry-based unique IDs.
- **Testing and observability**: PASS before design. The feature extends observability through the `price` attribute and requires deterministic tests for calculation plus entity publication.

### Post-Design Re-check

- **HA-first scope**: PASS after design. The contract remains a pair of read-only sensors built from existing Home Assistant price payloads.
- **Module separation**: PASS after design. The data model and structure keep day-scoped calculation generic and entity-layer concerns thin.
- **Controlled degradation**: PASS after design. `research.md`, `data-model.md`, `quickstart.md`, and the contract all require `unavailable` with omitted `price` when a valid 8-slot window cannot be proven for that day.
- **Naming and registry stability**: PASS after design. The design keeps stable IDs, translation keys, and existing Home Assistant naming rules for both sensors.
- **Testing and observability**: PASS after design. The updated artifacts require tests for average-price calculation, day isolation, buy-price invariance, and attribute omission while exposing richer observable state through `price`.

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
└── test_time_windows.py
```

**Structure Decision**: Keep the feature inside the existing `energy_optimizer` integration. Generalize the deterministic quarter-hour selector in `custom_components/energy_optimizer/calculations/price_windows.py` so it can evaluate either `prices_today` or `prices_tomorrow`, expose both payloads through shared coordinator state in `custom_components/energy_optimizer/coordinator.py`, keep the published today/tomorrow sensors in `custom_components/energy_optimizer/entities/sensors/pricing.py`, wire them through `custom_components/energy_optimizer/sensor.py`, and validate behavior with dedicated algorithm plus entity tests.

## Complexity Tracking

No constitution violations identified. The expanded feature still fits the current single-integration architecture without requiring exceptions.