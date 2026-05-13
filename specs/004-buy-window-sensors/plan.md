# Implementation Plan: Cztery Sensory Optymalnych Okien Zakupu Energii

**Branch**: `[004-buy-window-sensors]` | **Date**: 2026-05-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/004-buy-window-sensors/spec.md`

## Summary

Add four additive Home Assistant pricing sensors for the best two-hour buy windows: today night, today day, tomorrow night, and tomorrow day. The implementation will reuse coordinator-managed buy-price payloads `prices_today` and `prices_tomorrow`, extend `price_windows.py` with a pure two-hour minimum-average selector for buy windows, publish state as `HH:MM` with `price` and `is_negative` attributes, apply deterministic tie-breaking specific to night and day ranges, keep the affected slice `unavailable` when a full valid window cannot be formed, and preserve all existing sensors and pricing behavior unchanged.

## Technical Context

**Language/Version**: Python in the Home Assistant custom integration runtime  
**Primary Dependencies**: Home Assistant config entries, `DataUpdateCoordinator`, `CoordinatorEntity`/`SensorEntity`, existing Energy Optimizer sensor bases, translation files, pytest  
**Storage**: N/A for feature-specific persistence; all outputs are derived from coordinator-managed shared state  
**Testing**: `pytest` with focused calculation and entity tests under `tests/`  
**Target Platform**: Home Assistant custom integration distributed via HACS
**Project Type**: Single-project Home Assistant custom integration  
**Performance Goals**: Recompute all four derived sensors inside the existing refresh/listener path with negligible overhead by scanning at most the hourly buy-price entries already held for `prices_today` and `prices_tomorrow`  
**Constraints**: UI-only configuration; no blocking I/O; no new external APIs; buy-price data only; input payloads come from existing buy-price shared-state snapshots; each record must expose `time` and `price`; candidate starts are limited to full hours; windows last exactly 2 hours; night range is `00:00-06:00`; day range is `10:00-16:00`; state format is `HH:MM`; `price` rounds to 3 decimals; `is_negative` is true only when the selected average is below zero; empty `prices_tomorrow` keeps tomorrow sensors `unavailable`; translation-backed naming and stable config-entry-scoped unique IDs; no removal or regression of existing sensors  
**Scale/Scope**: Four additional derived sensors, one generalized buy-window selection core, additive entity publication beside the existing pricing sensors, translation updates, and targeted tests for range filtering, tie-breaks, day separation, attribute publication, and controlled degradation

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **HA-first scope**: PASS before design. The feature remains a read-only Home Assistant output derived from existing buy-price entities and does not add a parallel data source or control path.
- **Module separation**: PASS before design. The plan keeps window-selection logic in the calculations layer and limits Home Assistant publication concerns to pricing sensor entities and registration files.
- **Controlled degradation**: PASS before design. The spec requires per-slice `unavailable` behavior for missing or invalid two-hour candidates and explicitly treats empty `prices_tomorrow` as missing data for tomorrow only.
- **Naming and registry stability**: PASS before design. New sensors will stay translation-backed, inherit `_attr_has_entity_name = True`, keep stable unique IDs scoped to the config entry, and coexist with the current pricing sensor set.
- **Testing and observability**: PASS before design. The feature increases observability through explicit derived sensors and requires deterministic tests for calculation rules, attribute publication, and additive registration.

### Post-Design Re-check

- **HA-first scope**: PASS after design. `research.md`, `data-model.md`, and the contract keep the feature within additive HA-derived sensor publication using coordinator state as the sole source.
- **Module separation**: PASS after design. The design centralizes candidate parsing and two-hour selection helpers in `calculations/price_windows.py` while keeping `pricing.py` thin and declarative.
- **Controlled degradation**: PASS after design. The design requires `unavailable` for any slice without a complete valid two-hour window, isolates today/tomorrow and night/day behavior, and omits attributes whenever the sensor is unavailable.
- **Naming and registry stability**: PASS after design. The design uses four explicit translation-backed sensor variants with stable IDs and preserves the existing integration sensor surface.
- **Testing and observability**: PASS after design. The design adds explicit attribute publication, preserves deterministic tie-breaking, and requires targeted tests for both algorithmic and HA-facing behavior.

## Project Structure

### Documentation (this feature)

```text
specs/004-buy-window-sensors/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── buy-window-sensors.md
└── tasks.md
```

### Source Code (repository root)

```text
custom_components/energy_optimizer/
├── calculations/
│   └── price_windows.py
├── entities/
│   ├── base.py
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

**Structure Decision**: Keep the feature inside the existing `energy_optimizer` integration and reuse the current pricing sensor surface. Extend `custom_components/energy_optimizer/calculations/price_windows.py` with generalized buy-window helpers that consume hourly `prices_today` and `prices_tomorrow` payloads, form contiguous two-hour candidates, apply the night/day tie policies, and return a compact result object. Extend `custom_components/energy_optimizer/entities/sensors/pricing.py`, `custom_components/energy_optimizer/entities/sensors/__init__.py`, and `custom_components/energy_optimizer/sensor.py` with four buy-window sensor variants while preserving all existing sell-window and other pricing sensors, extend `custom_components/energy_optimizer/translations/en.json`, and validate behavior with focused calculation and entity tests plus additive registration regression coverage.

## Complexity Tracking

No constitution violations identified. The feature fits the current single-integration architecture without exceptions.
