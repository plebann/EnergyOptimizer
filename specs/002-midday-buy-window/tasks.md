# Tasks: Okno Najniższej Ceny Sprzedaży w Środku Dnia

**Input**: Design documents from `/specs/002-midday-buy-window/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/midday-buy-window-sensor.md, quickstart.md

**Tests**: Test tasks are REQUIRED for the quarter-hour window selection logic because this feature adds a decision path with hourly-to-quarter-hour expansion, shared-state payload access, tie-breaking, local-day scoping, and controlled degradation.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare feature files and exports used by all stories.

- [X] T001 Create feature scaffolding in `custom_components/energy_optimizer/calculations/price_windows.py` and `tests/test_price_windows.py`
- [X] T002 [P] Export the new calculation and sensor modules in `custom_components/energy_optimizer/calculations/__init__.py` and `custom_components/energy_optimizer/entities/sensors/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish shared-state payload access and platform wiring that every story depends on.

**⚠️ CRITICAL**: No user story work should start before this phase is complete.

- [X] T003 Extend shared coordinator state with the current-day hourly `sell-price sensor` payload in `custom_components/energy_optimizer/coordinator.py`
- [X] T004 [P] Build reusable hourly price payload fixtures and expanded quarter-hour expectations in `tests/test_price_windows.py`
- [X] T005 Add base platform registration for the midday sell window sensor in `custom_components/energy_optimizer/sensor.py`
- [X] T006 [P] Synchronize and validate `specs/002-midday-buy-window/contracts/midday-buy-window-sensor.md` against the implemented payload and output contract

**Checkpoint**: Foundation ready - the feature can now be delivered story by story.

---

## Phase 3: User Story 1 - Odczyt najtańszego okna sprzedaży w środku dnia (Priority: P1) 🎯 MVP

**Goal**: Publish a separate sensor that computes the cheapest current-day 8-quarter-hour sell-price window between 08:00 and 16:00 from hourly sell-price input expanded into quarter-hours.

**Independent Test**: With complete current-day hourly sell prices available, the new sensor publishes one correct midday window after expanding each hour into 4 quarter-hours and ignores tomorrow's prices.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T007 [P] [US1] Add full-data cheapest-window selection tests for the current local day from hourly input expanded into quarter-hours in `tests/test_price_windows.py`
- [X] T008 [P] [US1] Add entity publication tests for the separate midday sell window sensor in `tests/test_pricing_sensors.py`, including a regression check that buy-price-only changes do not affect the published window

### Implementation for User Story 1

- [X] T009 [US1] Implement current-day hourly sell-price parsing, quarter-hour expansion, and cheapest-window selection in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T010 [US1] Implement `MiddaySellWindowSensor` state calculation in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T011 [US1] Wire `MiddaySellWindowSensor` into `custom_components/energy_optimizer/entities/sensors/__init__.py` and `custom_components/energy_optimizer/sensor.py`

**Checkpoint**: User Story 1 should now publish a working midday sell window sensor for complete current-day data.

---

## Phase 4: User Story 2 - Użycie okna w automatyzacjach i decyzjach (Priority: P2)

**Goal**: Make the published sensor stable and automation-friendly through a consistent text format, translation-backed identity, and update behavior.

**Independent Test**: The sensor exposes a stable `HH:MM-HH:MM` value, has translation-backed naming, and refreshes when the shared-state sell-price payload changes.

### Tests for User Story 2

- [X] T012 [P] [US2] Add `HH:MM-HH:MM` format regression tests for the window sensor in `tests/test_pricing_sensors.py`
- [X] T013 [P] [US2] Add refresh-on-price-update regression tests for the window sensor in `tests/test_pricing_sensors.py`

### Implementation for User Story 2

- [X] T014 [US2] Finalize `HH:MM-HH:MM` formatting and 08:00-16:00 local-day bounds in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T015 [P] [US2] Add translation-backed metadata for the midday sell window sensor in `custom_components/energy_optimizer/entities/sensors/pricing.py` and `custom_components/energy_optimizer/translations/en.json`
- [X] T016 [US2] Refresh the midday sell window sensor from shared-state sell-price payload updates in `custom_components/energy_optimizer/sensor.py`

**Checkpoint**: User Stories 1 and 2 should now provide a stable, named, automation-ready midday window sensor.

---

## Phase 5: User Story 3 - Przewidywalne zachowanie przy brakach danych (Priority: P3)

**Goal**: Harden the feature so incomplete or invalid data never produces a misleading window and ties always resolve deterministically.

**Independent Test**: When the current-day price series is incomplete or invalid, the sensor becomes `unavailable`; when totals tie, the earliest valid window wins.

### Tests for User Story 3

- [X] T017 [P] [US3] Add insufficient-data and non-numeric hourly payload tests in `tests/test_price_windows.py`
- [X] T018 [P] [US3] Add tie-break and `unavailable` entity-state tests in `tests/test_price_windows.py` and `tests/test_pricing_sensors.py`

### Implementation for User Story 3

- [X] T019 [US3] Enforce `unavailable` on incomplete data and earliest-start tie-breaking in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T020 [US3] Ensure `MiddaySellWindowSensor` reads only shared-state sell-price data and maps invalid results to `unavailable` in `custom_components/energy_optimizer/entities/sensors/pricing.py`

**Checkpoint**: All user stories should now work with complete data, price updates, and failure-mode edge cases.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final documentation and focused validation across the completed feature.

- [X] T021 [P] Document the new midday sell window sensor in `README.md`
- [ ] T022 Run focused feature validation from `specs/002-midday-buy-window/quickstart.md` using `tests/test_price_windows.py` and `tests/test_pricing_sensors.py`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1: Setup**: No dependencies; can start immediately.
- **Phase 2: Foundational**: Depends on Phase 1 and blocks all story work.
- **Phase 3: User Story 1**: Depends on Phase 2 completion.
- **Phase 4: User Story 2**: Depends on Phase 3 because it extends the published sensor behavior.
- **Phase 5: User Story 3**: Depends on Phase 3 and should follow Phase 4 when possible because it hardens the final published behavior.
- **Phase 6: Polish**: Depends on all desired user stories being complete.

### User Story Dependencies

- **US1 (P1)**: First deliverable and MVP; no dependency on other stories once the foundational phase is complete.
- **US2 (P2)**: Builds on the working US1 sensor to make it stable for dashboards and automations.
- **US3 (P3)**: Builds on the US1 algorithm and published sensor to harden edge cases and deterministic behavior.

### Within Each User Story

- Tests MUST be written and fail before implementation changes.
- Shared-state and algorithm plumbing must be in place before entity logic relies on it.
- Calculation logic must be implemented before final entity wiring.
- Entity wiring must complete before story-level validation.

### Parallel Opportunities

- `T002` can run in parallel with `T001` after the new file paths are created.
- `T004` can run in parallel with `T003` during the foundational phase.
- `T007` and `T008` can run in parallel for US1.
- `T012` and `T013` can run in parallel for US2.
- `T015` can run in parallel with `T014` once the sensor contract is stable.
- `T017` and `T018` can run in parallel for US3.
- `T021` can run in parallel with `T022` once implementation is complete.

---

## Parallel Example: User Story 1

```bash
# Launch the story-1 tests together first
Task: "Add full-data cheapest-window selection tests in tests/test_price_windows.py"
Task: "Add entity publication and buy-price invariance tests in tests/test_pricing_sensors.py"
```

## Parallel Example: User Story 2

```bash
# Run formatting and update-path checks in parallel
Task: "Add HH:MM-HH:MM format regression tests in tests/test_pricing_sensors.py"
Task: "Add refresh-on-price-update regression tests for the window sensor in tests/test_pricing_sensors.py"
```

## Parallel Example: User Story 3

```bash
# Harden calculation and entity behavior together through parallel tests
Task: "Add insufficient-data and non-numeric hourly payload tests in tests/test_price_windows.py"
Task: "Add tie-break and unavailable entity-state tests in tests/test_price_windows.py and tests/test_pricing_sensors.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational.
3. Complete Phase 3: User Story 1.
4. Stop and validate the new midday sell window sensor against complete current-day price data.

### Incremental Delivery

1. Deliver US1 to get the basic sensor published.
2. Deliver US2 to stabilize formatting, naming, and refresh behavior.
3. Deliver US3 to harden insufficient-data and tie-break behavior.
4. Finish with documentation and focused validation.

### Parallel Team Strategy

1. One developer handles shared-state hourly sell-price payload access in `custom_components/energy_optimizer/coordinator.py` and hour-to-quarter-hour expansion in `custom_components/energy_optimizer/calculations/price_windows.py` while another prepares shared hourly fixtures and expanded quarter-hour expectations in `tests/test_price_windows.py`.
2. After the foundational phase, one developer can work on calculation logic while another prepares entity-level tests.
3. Translation/documentation work can proceed in parallel with the final validation step.

---

## Notes

- `[P]` tasks touch different files or can proceed independently after prerequisites are met.
- Story labels map each task directly to `spec.md` user stories for traceability.
- The MVP is User Story 1.
- Focused validation should prefer the quickstart commands and story-specific tests before any broader test suite.