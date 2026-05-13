# Implementation Plan: Cztery Sensory Optymalnych Okien Sprzedazy Energii

**Branch**: `[003-add-sell-window-sensors]` | **Date**: 2026-05-12 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-sell-window-sensors/spec.md`

## Summary

Add four ranked one-hour sell-window sensors alongside the existing pricing sensors: today morning, today evening, tomorrow morning, and tomorrow evening. The implementation will reuse coordinator-managed `prices_today` and `prices_tomorrow` payloads, refactor the existing specialized midday selector into a generalized hourly max-price ranking helper, publish state as `HH:MM`, add `price`, `second_window_start`, `second_window_price`, and `second_window_gap_pct` attributes with explicit rounding, preserve earliest-start tie-breaking, degrade to `unavailable` when fewer than two valid hourly candidates exist for a sensor's day/range slice, and keep all existing sensors available and functionally unchanged.

## Technical Context

**Language/Version**: Python in the Home Assistant custom integration runtime  
**Primary Dependencies**: Home Assistant config entries, `DataUpdateCoordinator`, `CoordinatorEntity`/`SensorEntity`, existing Energy Optimizer sensor bases, translation files, pytest  
**Storage**: N/A for feature-specific persistence; all outputs are derived from coordinator-managed shared state  
**Testing**: `pytest` with focused calculation and entity tests under `tests/`  
**Target Platform**: Home Assistant custom integration distributed via HACS  
**Project Type**: Single-project Home Assistant custom integration  
**Performance Goals**: Recompute all four derived sensors inside the existing refresh/listener path with negligible overhead by scanning at most the hourly sell-price entries already held for `prices_today` and `prices_tomorrow`  
**Constraints**: UI-only configuration; no blocking I/O; no new external APIs; sell-price data only; one input price per full hour; candidate windows start only on full hours; morning range is `04:00-10:00`, evening range is `16:00-22:00`; state format is `HH:MM`; `price` and `second_window_price` round to 3 decimals; `second_window_gap_pct` rounds to 1 decimal; sensor is `unavailable` unless both best and second-best windows are valid; translation-backed naming and stable config-entry-scoped unique IDs; no removal or functional regression of existing sensors; buy-window sensors remain out of scope for this feature  
**Scale/Scope**: Four additional derived sensors, one generalized ranking core, additive entity publication beside the existing pricing sensors, translation updates, and targeted tests for ranking, tie-breaks, day separation, coexistence, and controlled degradation

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **HA-first scope**: PASS before design. The feature remains a read-only Home Assistant output derived from existing sell-price entities and does not add a parallel data source or control path.
- **Module separation**: PASS before design. The plan keeps ranking logic in the calculations layer and limits Home Assistant publishing concerns to sensor entities and registration files.
- **Controlled degradation**: PASS before design. The spec requires `unavailable` when fewer than two valid candidates exist and omits only the percentage attribute when the best price is zero.
- **Naming and registry stability**: PASS before design. New sensors will stay translation-backed, `_attr_has_entity_name = True`, keep stable unique IDs scoped to the config entry, and coexist with the current sensor set.
- **Testing and observability**: PASS before design. The feature increases observability through ranked comparison attributes and requires deterministic tests for calculation and entity publication.

### Post-Design Re-check

- **HA-first scope**: PASS after design. `research.md`, `data-model.md`, and the contract keep the feature within additive HA-derived sensor publication using coordinator state as the sole source.
- **Module separation**: PASS after design. The design centralizes ranking and formatting helpers in `calculations/price_windows.py` while keeping `pricing.py` thin and declarative.
- **Controlled degradation**: PASS after design. The design requires `unavailable` for missing top-two candidates, independent day/range evaluation, and omission of `second_window_gap_pct` only when the best price is zero.
- **Naming and registry stability**: PASS after design. The design uses four explicit translation-backed sensor variants with stable IDs and preserves the existing integration sensor surface.
- **Testing and observability**: PASS after design. The design adds richer attributes, preserves deterministic tie-breaking, and requires targeted tests for both algorithmic and HA-facing behavior.

## Project Structure

### Documentation (this feature)

```text
specs/003-sell-window-sensors/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── sell-window-sensors.md
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
└── test_services_registration.py
```

**Structure Decision**: Keep the feature inside the existing `energy_optimizer` integration and reuse the current pricing sensor surface. Refactor `custom_components/energy_optimizer/calculations/price_windows.py` from a midday cheapest-quarter-hour selector into a generalized hourly sell-window ranking helper that can evaluate morning or evening ranges for either `prices_today` or `prices_tomorrow`. Extend `custom_components/energy_optimizer/entities/sensors/pricing.py`, `custom_components/energy_optimizer/entities/sensors/__init__.py`, and `custom_components/energy_optimizer/sensor.py` with four ranked one-hour sensors while preserving the existing midday and other pricing sensors, extend `custom_components/energy_optimizer/translations/en.json`, and validate behavior with focused algorithm and entity tests plus coexistence regressions.

## Complexity Tracking

No constitution violations identified. The feature fits the current single-integration architecture without exceptions.
