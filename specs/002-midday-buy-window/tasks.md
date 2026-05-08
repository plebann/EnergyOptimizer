# Tasks: Okno Najniższej Ceny Sprzedaży w Środku Dnia

**Input**: Design documents from `/specs/002-midday-buy-window/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/midday-buy-window-sensor.md, quickstart.md

**Tests**: Test tasks are REQUIRED for the quarter-hour window selection logic because this feature adds a new decision path with tie-breaking, local-day scoping, and controlled degradation.

**Organization**: Tasks are grouped by user story to preserve independent delivery and validation for each increment.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare the feature-specific files and shared scaffolding used by all stories.

- [ ] T001 Create feature scaffolding in custom_components/energy_optimizer/calculations/price_windows.py and tests/test_price_windows.py
- [ ] T002 [P] Export the new calculation and sensor modules in custom_components/energy_optimizer/calculations/__init__.py and custom_components/energy_optimizer/entities/sensors/__init__.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the raw price-series access and platform wiring that every story depends on.

**⚠️ CRITICAL**: No user story work should start before this phase is complete.

- [ ] T003 Add direct Home Assistant state-object reading for current-day sell price-series payload in custom_components/energy_optimizer/calculations/price_windows.py
- [ ] T004 [P] Build reusable quarter-hour price payload fixtures in tests/test_price_windows.py
- [ ] T005 Add base platform registration for the midday sell window sensor in custom_components/energy_optimizer/sensor.py

**Checkpoint**: Foundation ready - the feature can now be delivered story by story.

---

## Phase 3: User Story 1 - Odczyt najtańszego okna sprzedaży w środku dnia (Priority: P1) 🎯 MVP

**Goal**: Publish a separate sensor that computes the cheapest current-day 8-quarter-hour sell-price window between 08:00 and 16:00.

**Independent Test**: With complete current-day quarter-hour sell prices available, the new sensor publishes one correct midday window and ignores tomorrow's prices.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T006 [P] [US1] Add full-data cheapest-window selection tests for the current local day in tests/test_price_windows.py
- [ ] T007 [P] [US1] Add entity publication tests for the separate midday sell window sensor in tests/test_pricing_sensors.py

### Implementation for User Story 1

- [ ] T008 [US1] Implement current-day quarter-hour sell-price parsing and cheapest-window selection in custom_components/energy_optimizer/calculations/price_windows.py
- [ ] T009 [US1] Implement MiddayBuyWindowSensor state calculation in custom_components/energy_optimizer/entities/sensors/pricing.py
- [ ] T010 [US1] Wire MiddayBuyWindowSensor into custom_components/energy_optimizer/entities/sensors/__init__.py and custom_components/energy_optimizer/sensor.py

**Checkpoint**: User Story 1 should now publish a working midday sell window sensor for complete current-day data.

---

## Phase 4: User Story 2 - Użycie okna w automatyzacjach i decyzjach (Priority: P2)

**Goal**: Make the published sensor stable and automation-friendly through a consistent text format, translation-backed identity, and update behavior.

**Independent Test**: The sensor exposes a stable `HH:MM-HH-MM` value, has translation-backed naming, and refreshes when the price-series source changes.

### Tests for User Story 2

- [ ] T011 [P] [US2] Add `HH:MM-HH-MM` format regression tests for the window sensor in tests/test_pricing_sensors.py
- [ ] T012 [P] [US2] Add refresh-on-price-update regression tests for the window sensor in tests/test_pricing_sensors.py

### Implementation for User Story 2

- [ ] T013 [US2] Finalize `HH:MM-HH-MM` formatting and 08:00-16:00 local-day bounds in custom_components/energy_optimizer/calculations/price_windows.py
- [ ] T014 [P] [US2] Add translation-backed metadata for the midday sell window sensor in custom_components/energy_optimizer/entities/sensors/pricing.py and custom_components/energy_optimizer/translations/en.json
- [ ] T015 [US2] Refresh the midday sell window sensor from price-source change events in custom_components/energy_optimizer/sensor.py

**Checkpoint**: User Stories 1 and 2 should now provide a stable, named, automation-ready midday window sensor.

---

## Phase 5: User Story 3 - Przewidywalne zachowanie przy brakach danych (Priority: P3)

**Goal**: Harden the feature so incomplete or invalid data never produces a misleading window and ties always resolve deterministically.

**Independent Test**: When the current-day price series is incomplete or invalid, the sensor becomes `unavailable`; when totals tie, the earliest valid window wins.

### Tests for User Story 3

- [ ] T016 [P] [US3] Add insufficient-data and non-numeric payload tests in tests/test_price_windows.py
- [ ] T017 [P] [US3] Add tie-break and `unavailable` entity-state tests in tests/test_price_windows.py and tests/test_pricing_sensors.py

### Implementation for User Story 3

- [ ] T018 [US3] Enforce `unavailable` on incomplete data and earliest-start tie-breaking in custom_components/energy_optimizer/calculations/price_windows.py
- [ ] T019 [US3] Ensure MiddayBuyWindowSensor reads only sell-price series and maps invalid results to `unavailable` in custom_components/energy_optimizer/entities/sensors/pricing.py

**Checkpoint**: All user stories should now work with complete data, price updates, and failure-mode edge cases.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final documentation and focused validation across the completed feature.

- [ ] T020 [P] Document the new midday sell window sensor in README.md
- [ ] T021 Run focused feature validation from specs/002-midday-buy-window/quickstart.md using tests/test_price_windows.py and tests/test_pricing_sensors.py

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
- Calculation logic must be implemented before final entity wiring.
- Entity wiring must complete before story-level validation.

### Parallel Opportunities

- `T002` can run in parallel with `T001` after the new file paths are created.
- `T004` can run in parallel with `T003` during the foundational phase.
- `T006` and `T007` can run in parallel for US1.
- `T011` and `T012` can run in parallel for US2.
- `T014` can run in parallel with `T013` once the sensor contract is stable.
- `T016` and `T017` can run in parallel for US3.
- `T020` can run in parallel with `T021` once implementation is complete.

---

## Parallel Example: User Story 1

```bash
# Launch the story-1 tests together first
Task: "Add full-data cheapest-window selection tests in tests/test_price_windows.py"
Task: "Add entity publication tests for the separate midday sell window sensor in tests/test_pricing_sensors.py"
```

## Parallel Example: User Story 2

```bash
# Run formatting and update-path checks in parallel
Task: "Add HH:MM-HH-MM format regression tests in tests/test_pricing_sensors.py"
Task: "Add refresh-on-price-update regression tests in tests/test_pricing_sensors.py"
```

## Parallel Example: User Story 3

```bash
# Harden calculation and entity behavior together through parallel tests
Task: "Add insufficient-data and non-numeric payload tests in tests/test_price_windows.py"
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

1. One developer handles direct HA state-object price-series access in `custom_components/energy_optimizer/calculations/price_windows.py` while another prepares shared quarter-hour fixtures in `tests/test_price_windows.py`.
2. After the foundational phase, one developer can work on calculation logic while another prepares entity-level tests.
3. Translation/documentation work can proceed in parallel with the final validation step.

---

## Notes

- `[P]` tasks touch different files or can proceed independently after prerequisites are met.
- Story labels map each task directly to `spec.md` user stories for traceability.
- The MVP is User Story 1.
- Focused validation should prefer the quickstart commands and story-specific tests before any broader test suite.