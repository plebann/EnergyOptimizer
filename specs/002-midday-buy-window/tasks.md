# Tasks: Rozszerzenie Sensorów Okna Najniższej Ceny Sprzedaży

**Input**: Design documents from `/specs/002-midday-buy-window/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/midday-buy-window-sensor.md, quickstart.md

**Tests**: Test tasks are REQUIRED because this feature extends a decision path with day-scoped payload selection, average-price calculation, tie-breaking, and `unavailable` behavior across two derived sensors.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare the file surfaces and shared test scaffolding used by all stories.

- [X] T001 Create dual-day price-window scaffolding in `custom_components/energy_optimizer/calculations/price_windows.py` and `tests/test_price_windows.py`
- [X] T002 [P] Prepare derived sensor scaffolding for today/tomorrow variants in `custom_components/energy_optimizer/entities/sensors/pricing.py` and `tests/test_pricing_sensors.py`
- [X] T003 [P] Add translation placeholders and sensor exports for the new variants in `custom_components/energy_optimizer/entities/sensors/__init__.py` and `custom_components/energy_optimizer/translations/en.json`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish shared-state payload access and reusable selection plumbing required by every story.

**⚠️ CRITICAL**: No user story work should start before this phase is complete.

- [X] T004 Extend shared coordinator state with `prices_today` and `prices_tomorrow` sell-price payload snapshots in `custom_components/energy_optimizer/coordinator.py`
- [X] T005 [P] Add reusable today/tomorrow hourly payload fixtures and expected quarter-hour expansions in `tests/test_price_windows.py` and `tests/test_pricing_sensors.py`
- [X] T006 Build the shared day-scoped window result contract and parser entry points in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T007 Wire base sensor-platform registration for day-scoped midday sell-window entities in `custom_components/energy_optimizer/sensor.py` and `custom_components/energy_optimizer/entities/sensors/__init__.py`

**Checkpoint**: Foundation ready - the feature can now be delivered story by story.

---

## Phase 3: User Story 1 - Odczyt najtańszego okna sprzedaży z ceną średnią (Priority: P1) 🎯 MVP

**Goal**: Keep the current-day midday sell-window sensor working while adding the `price` attribute with the rounded average selected-window price.

**Independent Test**: With complete `prices_today` sell-price data available, the existing current-day sensor publishes the same `HH:MM-HH:MM` window as before plus a rounded float `price` attribute in PLN/kWh.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T008 [P] [US1] Add current-day average-price selection tests from `prices_today` in `tests/test_price_windows.py`
- [X] T009 [P] [US1] Add current-day entity publication tests for state and `price` in `tests/test_pricing_sensors.py`

### Implementation for User Story 1

- [X] T010 [US1] Implement current-day window selection with average-price calculation in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T011 [US1] Implement the current-day midday sell-window sensor state and `price` attribute in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T012 [US1] Register current-day translation-backed metadata and platform wiring in `custom_components/energy_optimizer/sensor.py` and `custom_components/energy_optimizer/translations/en.json`

**Checkpoint**: User Story 1 should now publish the current-day window sensor with the new `price` attribute.

---

## Phase 4: User Story 2 - Odczyt analogicznego okna dla jutra (Priority: P2)

**Goal**: Publish a second sensor for tomorrow that applies the same window-selection and `price` rules using only `prices_tomorrow`.

**Independent Test**: With complete `prices_tomorrow` sell-price data available, the integration publishes a separate tomorrow sensor with the correct `HH:MM-HH:MM` state and rounded `price`, without altering the current-day sensor.

### Tests for User Story 2

- [X] T013 [P] [US2] Add tomorrow-payload window selection tests from `prices_tomorrow` in `tests/test_price_windows.py`
- [X] T014 [P] [US2] Add tomorrow sensor publication and day-isolation tests in `tests/test_pricing_sensors.py`

### Implementation for User Story 2

- [X] T015 [US2] Generalize the selector for `prices_tomorrow` with the same day-scoped rules in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T016 [US2] Implement the tomorrow midday sell-window sensor and its translation-backed metadata in `custom_components/energy_optimizer/entities/sensors/pricing.py` and `custom_components/energy_optimizer/translations/en.json`
- [X] T017 [US2] Register the tomorrow sensor and isolate refresh behavior to day-scoped payload changes in `custom_components/energy_optimizer/sensor.py` and `custom_components/energy_optimizer/coordinator.py`

**Checkpoint**: User Stories 1 and 2 should now expose separate today/tomorrow sensors with matching rules.

---

## Phase 5: User Story 3 - Zachowanie bez zmian poza nowym zakresem danych (Priority: P3)

**Goal**: Preserve deterministic tie-breaking and controlled degradation so invalid data never publishes a misleading window or stale `price`.

**Independent Test**: When data for one day is incomplete or invalid, only that sensor becomes `unavailable` and omits `price`; when totals tie, the earliest valid window still wins.

### Tests for User Story 3

- [X] T018 [P] [US3] Add insufficient-data, tie-break, and omitted-`price` tests for both day scopes in `tests/test_price_windows.py`
- [X] T019 [P] [US3] Add entity regression tests for buy-price invariance, `unavailable`, and missing `price` in `tests/test_pricing_sensors.py`

### Implementation for User Story 3

- [X] T020 [US3] Enforce earliest-start tie-breaking and invalid-result mapping for both day scopes in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T021 [US3] Omit `price` on `unavailable` and keep sell-price-only reads in `custom_components/energy_optimizer/entities/sensors/pricing.py` and `custom_components/energy_optimizer/sensor.py`

**Checkpoint**: All user stories should now work with complete data, isolated day updates, and failure-mode edge cases.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final documentation and focused validation across the completed feature.

- [X] T022 [P] Update user-facing documentation for today/tomorrow sensors and `price` in `README.md`
- [X] T023 Run focused feature validation from `specs/002-midday-buy-window/quickstart.md` using `tests/test_price_windows.py` and `tests/test_pricing_sensors.py`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1: Setup**: No dependencies; can start immediately.
- **Phase 2: Foundational**: Depends on Phase 1 and blocks all user stories.
- **Phase 3: User Story 1**: Depends on Phase 2 completion.
- **Phase 4: User Story 2**: Depends on Phase 2 and reuses the shared selector pattern established in US1.
- **Phase 5: User Story 3**: Depends on the core behavior from US1 and US2 so hardening covers both day-scoped sensors.
- **Phase 6: Polish**: Depends on all desired user stories being complete.

### User Story Dependencies

- **User Story 1 (P1)**: First deliverable and MVP; no dependency on other user stories once the foundational phase is complete.
- **User Story 2 (P2)**: Can begin after the foundational phase, but it shares calculation and entity files with US1, so coordinate sequencing when one developer owns those files.
- **User Story 3 (P3)**: Builds on the completed today/tomorrow sensor behavior to harden degradation, tie-breaking, and attribute omission.

### Within Each User Story

- Tests MUST be written and fail before implementation changes.
- Shared calculation behavior must be updated before entity publication relies on it.
- Entity logic must be in place before translation or platform wiring is considered complete.
- Story-level validation should run before moving to the next priority.

### Parallel Opportunities

- `T002` and `T003` can run in parallel after `T001` establishes the feature surface.
- `T005` can run in parallel with `T004` during the foundational phase.
- `T008` and `T009` can run in parallel for US1.
- `T013` and `T014` can run in parallel for US2.
- `T018` and `T019` can run in parallel for US3.
- `T022` can run in parallel with `T023` once implementation is complete.

---

## Parallel Example: User Story 1

```bash
# Launch the current-day tests together first
Task: "Add current-day average-price selection tests in tests/test_price_windows.py"
Task: "Add current-day entity publication tests for state and price in tests/test_pricing_sensors.py"
```

## Parallel Example: User Story 2

```bash
# Verify tomorrow behavior and day isolation in parallel
Task: "Add tomorrow-payload window selection tests in tests/test_price_windows.py"
Task: "Add tomorrow sensor publication and day-isolation tests in tests/test_pricing_sensors.py"
```

## Parallel Example: User Story 3

```bash
# Harden failure modes across the calculation and entity layers in parallel
Task: "Add insufficient-data, tie-break, and omitted-price tests in tests/test_price_windows.py"
Task: "Add entity regression tests for buy-price invariance, unavailable, and missing price in tests/test_pricing_sensors.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational.
3. Complete Phase 3: User Story 1.
4. Stop and validate the current-day sensor against complete `prices_today` data and the new `price` attribute.

### Incremental Delivery

1. Deliver US1 to extend the existing sensor with `price`.
2. Deliver US2 to add the tomorrow sensor with the same rules.
3. Deliver US3 to harden day isolation, tie-breaking, and `unavailable` behavior.
4. Finish with documentation and focused validation.

### Parallel Team Strategy

1. One developer can handle coordinator/shared-state payload access in `custom_components/energy_optimizer/coordinator.py` while another prepares day-scoped fixtures and expected window outputs in `tests/test_price_windows.py`.
2. After the foundational phase, one developer can focus on calculation logic in `custom_components/energy_optimizer/calculations/price_windows.py` while another prepares entity publication tests in `tests/test_pricing_sensors.py`.
3. Documentation work in `README.md` can proceed in parallel with the final focused validation step.

---

## Notes

- `[P]` tasks touch different files or can proceed independently after prerequisites are complete.
- Story labels map each task directly to `spec.md` user stories for traceability.
- The MVP is User Story 1.
- Focused validation should prefer the quickstart command set and story-specific tests before broader suites.