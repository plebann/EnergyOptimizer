# Implementation Plan: Okno Najniższej Ceny Sprzedaży w Środku Dnia

**Branch**: `[002-midday-buy-window]` | **Date**: 2026-05-07 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-midday-buy-window/spec.md`

## Summary

Add a derived Home Assistant text sensor that publishes the cheapest current-day sell-price window between 08:00 and 16:00, using exactly 8 contiguous quarter-hour slots and formatting the result as `HH:MM-HH:MM`. The implementation will keep the selection algorithm in a pure calculation module, read hourly `sell-price sensor` data from shared integration state, expand each full hour into 4 quarter-hour slots with the same price, publish `unavailable` on insufficient data, and integrate through the current entity/translation/test patterns already used by `energy_optimizer`.

## Technical Context

**Language/Version**: Python in the Home Assistant custom integration runtime (repo does not pin a separate standalone interpreter version)  
**Primary Dependencies**: Home Assistant config entries, `DataUpdateCoordinator`, `CoordinatorEntity`/`SensorEntity`, existing Energy Optimizer entity bases and translations, pytest  
**Storage**: N/A for feature-specific persistence; state is derived from current Home Assistant entity state and attributes  
**Testing**: `pytest` with focused unit tests under `tests/`  
**Target Platform**: Home Assistant custom integration distributed via HACS  
**Project Type**: Single-project Home Assistant custom integration  
**Performance Goals**: Recompute the midday window inside the existing refresh/listener path with negligible overhead by scanning only the current local day hourly payload already stored in shared integration state and expanding it in memory to quarter-hour slots  
**Constraints**: UI-only configuration, no blocking I/O, no new external APIs, current local day only, `sell-price sensor` only, hourly input expanded into 4 quarter-hours per hour, shared-state access instead of direct entity reads from the output sensor, earliest-window tie-break, `unavailable` on insufficient data, translation-backed naming, stable unique IDs tied to the config entry  
**Scale/Scope**: One new derived sensor, one pure calculation module, one focused output contract, one translation update, and targeted test additions

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **HA-first scope**: PASS before design. The feature remains a derived Home Assistant sensor and does not introduce direct device control or external telemetry responsibilities.
- **Module separation**: PASS before design. The plan keeps pricing-window selection in a calculation module and leaves entity registration and HA publishing in platform/entity files.
- **Controlled degradation**: PASS before design. The design explicitly maps insufficient or invalid input data to `unavailable` instead of a stale or guessed window.
- **Naming and registry stability**: PASS before design. The new entity will use `translation_key`, `_attr_has_entity_name = True`, and a stable config-entry-prefixed unique ID.
- **Testing and observability**: PASS before design. The feature itself is the observable output, and the plan includes deterministic algorithm and entity tests.

### Post-Design Re-check

- **HA-first scope**: PASS after design. The contract remains a read-only sensor built from existing Home Assistant price entities.
- **Module separation**: PASS after design. The proposed file layout keeps the pure selector in `calculations/` and the published sensor in `entities/sensors/`.
- **Controlled degradation**: PASS after design. The data model and contract both require `unavailable` whenever a full 8-slot window cannot be proven from valid current-day data.
- **Naming and registry stability**: PASS after design. The plan routes entity naming through translations and existing base-entity unique-ID behavior.
- **Testing and observability**: PASS after design. `research.md`, `data-model.md`, `quickstart.md`, and the contract define the expected observable state and the required regression coverage.

## Implementation Strategy

1. Add a pure parser/selector for current-day hourly `sell-price sensor` points from shared state, expand each hour into 4 quarter-hour slots with the same price, and choose the cheapest contiguous 8-slot window between 08:00 and 16:00.
2. Add a dedicated text sensor that formats the chosen window as `HH:MM-HH:MM` and becomes `unavailable` when the selector cannot return a valid result.
3. Extend the shared integration state so the coordinator exposes the hourly `sell-price sensor` payload while reusing the existing refresh/listener path for pricing changes.
4. Add translation, contract, and focused regression tests for tie-breaking, insufficient data, and current-day-only filtering.

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
├── const.py
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

**Structure Decision**: Keep the feature inside the existing `energy_optimizer` integration. Put deterministic quarter-hour window selection in a new `custom_components/energy_optimizer/calculations/price_windows.py` module, normalize hourly shared-state data into quarter-hour candidates there, keep the published sensor inside `custom_components/energy_optimizer/entities/sensors/pricing.py`, wire it through `custom_components/energy_optimizer/sensor.py`, and expose the hourly `sell-price sensor` payload through shared coordinator state instead of direct entity reads from the result sensor. Add a dedicated algorithm test file and extend existing pricing sensor tests for entity behavior.

## Complexity Tracking

No constitution violations identified. This feature fits the current single-integration architecture without requiring additional exceptions.
