# Tasks: Cztery Sensory Optymalnych Okien Sprzedazy Energii

**Input**: Design documents from `/specs/003-sell-window-sensors/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/sell-window-sensors.md`, `quickstart.md`

**Tests**: Test tasks are REQUIRED because this feature changes a pricing decision path, extends the published sensor surface, and adds ranking, tie-break, rounding, degradation, and coexistence rules.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare the shared file surfaces and test scaffolding used by all stories.

- [x] T001 Prepare ranked sell-window fixture helpers in `tests/test_price_windows.py`
- [x] T002 [P] Prepare ranked pricing sensor fixture helpers in `tests/test_pricing_sensors.py`
- [x] T003 [P] Preserve existing midday translation strings while adding placeholder ranked sell-window keys in `custom_components/energy_optimizer/translations/en.json`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the shared ranking and entity plumbing required before any specific story can be completed.

**⚠️ CRITICAL**: No user story work should begin until this phase is complete.

- [x] T004 Refactor hourly sell-price parsing, full-hour filtering, range constants, and ranking result types in `custom_components/energy_optimizer/calculations/price_windows.py`
- [x] T005 Implement shared ranked sell-window sensor base behavior in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [x] T006 [P] Preserve coexistence of existing midday sensor exports while preparing ranked pricing sensor exports in `custom_components/energy_optimizer/entities/sensors/__init__.py`
- [x] T007 [P] Preserve coexistence of existing midday sensor registration while preparing ranked pricing sensor registration slots in `custom_components/energy_optimizer/sensor.py`

**Checkpoint**: Foundation ready - story implementation can proceed.

---

## Phase 3: User Story 1 - Dzisiejsze okna sprzedazy (Priority: P1) 🎯 MVP

**Goal**: Publish today morning and today evening ranked sell-window sensors with the best window start time and runner-up comparison attributes.

**Independent Test**: With complete `prices_today` data, the integration publishes two sensors for today whose states are `HH:MM` and whose attributes expose `price`, `second_window_start`, `second_window_price`, and `second_window_gap_pct` with the required rounding when valid.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T008 [P] [US1] Add today morning and evening ranking, full-hour filtering, and rounding tests in `tests/test_price_windows.py`
- [x] T009 [P] [US1] Add today morning and evening sensor publication contract tests plus existing midday output contract regression checks in `tests/test_pricing_sensors.py`

### Implementation for User Story 1

- [x] T010 [US1] Implement today morning and evening candidate selection, full-hour filtering, and ranking output shaping in `custom_components/energy_optimizer/calculations/price_windows.py`
- [x] T011 [US1] Implement today morning and evening ranked sensor entities with `second_window_*` attributes in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [x] T012 [US1] Register today ranked sell-window sensors in `custom_components/energy_optimizer/sensor.py`
- [x] T013 [US1] Finalize today ranked sell-window translations in `custom_components/energy_optimizer/translations/en.json`

**Checkpoint**: User Story 1 should now expose both ranked today sensors and be independently testable.

---

## Phase 4: User Story 2 - Jutrzejsze okna sprzedazy (Priority: P2)

**Goal**: Publish tomorrow morning and tomorrow evening ranked sell-window sensors using only `prices_tomorrow` data.

**Independent Test**: With complete `prices_tomorrow` data, the integration publishes two tomorrow sensors with the same `HH:MM` state contract and attributes `price`, `second_window_start`, `second_window_price`, and `second_window_gap_pct`, without affecting the today sensors or the existing sensor set.

### Tests for User Story 2

- [x] T014 [P] [US2] Add tomorrow day-scoping and payload-isolation ranking tests in `tests/test_price_windows.py`
- [x] T015 [P] [US2] Add tomorrow morning and evening sensor publication isolation tests in `tests/test_pricing_sensors.py`

### Implementation for User Story 2

- [x] T016 [US2] Implement tomorrow payload selection and day-offset handling in `custom_components/energy_optimizer/calculations/price_windows.py`
- [x] T017 [US2] Implement tomorrow morning and evening ranked sensor entities in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [x] T018 [US2] Register tomorrow ranked sell-window sensors in `custom_components/energy_optimizer/sensor.py`
- [x] T019 [US2] Finalize tomorrow ranked sell-window translations in `custom_components/energy_optimizer/translations/en.json`

**Checkpoint**: User Stories 1 and 2 should now expose four ranked sensors across both days.

---

## Phase 5: User Story 3 - Przewidywalny ranking i degradacja danych (Priority: P3)

**Goal**: Enforce deterministic tie-breaking, strict top-two availability rules, safe attribute omission for invalid or zero-based comparisons, and no regressions in existing sensors.

**Independent Test**: With tied prices, missing candidates, invalid prices, or a best price of zero, the shared ranking logic and published entities still produce deterministic results and never publish misleading partial output, while existing sensors remain present and unchanged.

### Tests for User Story 3

- [x] T020 [P] [US3] Add tie-break, missing-runner-up, invalid-price, zero-best-price gap omission, and existing midday calculation regression tests in `tests/test_price_windows.py`
- [x] T021 [P] [US3] Add unavailable-state, buy-price-invariance, and existing midday sensor behavior regression tests in `tests/test_pricing_sensors.py`

### Implementation for User Story 3

- [x] T022 [US3] Enforce earliest-start tie-breaking and top-two availability rules in `custom_components/energy_optimizer/calculations/price_windows.py`
- [x] T023 [US3] Apply unavailable-state and `second_window_gap_pct` omission behavior in `custom_components/energy_optimizer/entities/sensors/pricing.py`

**Checkpoint**: All ranked sensor variants should now behave deterministically across edge cases and coexist cleanly with the existing sensors.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final documentation and focused validation across the completed feature.

- [x] T024 Run quickstart validation commands for `tests/test_price_windows.py` and `tests/test_pricing_sensors.py` from `specs/003-sell-window-sensors/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion - blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational completion.
- **User Story 2 (Phase 4)**: Depends on Foundational completion.
- **User Story 3 (Phase 5)**: Depends on Foundational completion and hardens the shared ranking behavior used by all sensor variants.
- **Polish (Phase 6)**: Depends on all desired user stories being complete.

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational completion - MVP and no dependency on other stories.
- **User Story 2 (P2)**: Can start after Foundational completion - should remain independently testable even though it reuses the same shared ranking files.
- **User Story 3 (P3)**: Can start after Foundational completion - should remain independently testable through tie-break and degradation scenarios on the shared ranking contract.

### Within Each User Story

- Tests MUST be written and fail before implementation.
- Shared ranking logic changes should land before entity publication depends on them.
- Entity publication should land before registration and translation finalization.
- Story-specific validation should run before moving to the next priority.

### Parallel Opportunities

- `T002` and `T003` can run in parallel after `T001` begins the shared test scaffolding.
- `T006` and `T007` can run in parallel after `T005` defines the ranked sensor base shape.
- `T008` and `T009` can run in parallel for User Story 1.
- `T014` and `T015` can run in parallel for User Story 2.
- `T020` and `T021` can run in parallel for User Story 3.
- `T024` runs after implementation is complete and the quickstart validation commands are ready.

---

## Parallel Example: User Story 1

```bash
# Launch the today-specific tests together first
Task: "Add today morning and evening ranking, full-hour filtering, and rounding tests in tests/test_price_windows.py"
Task: "Add today morning and evening sensor publication contract tests plus existing midday output contract regression checks in tests/test_pricing_sensors.py"
```

## Parallel Example: User Story 2

```bash
# Validate tomorrow behavior and day isolation in parallel
Task: "Add tomorrow day-scoping and payload-isolation ranking tests in tests/test_price_windows.py"
Task: "Add tomorrow morning and evening sensor publication isolation tests in tests/test_pricing_sensors.py"
```

## Parallel Example: User Story 3

```bash
# Harden ranking edge cases in parallel
Task: "Add tie-break, missing-runner-up, invalid-price, zero-best-price gap omission, and existing midday calculation regression tests in tests/test_price_windows.py"
Task: "Add unavailable-state, buy-price-invariance, and existing midday sensor behavior regression tests in tests/test_pricing_sensors.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational.
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: Confirm the two today sensors work independently with `prices_today`.

### Incremental Delivery

1. Complete Setup + Foundational.
2. Deliver User Story 1 and validate today-only behavior.
3. Deliver User Story 2 and validate tomorrow isolation.
4. Deliver User Story 3 and validate edge cases and coexistence behavior.
5. Finish with focused regression validation.

### Parallel Team Strategy

1. One developer can prepare ranking fixtures in `tests/test_price_windows.py` while another prepares entity fixtures in `tests/test_pricing_sensors.py`.
2. After Foundational completion, one developer can focus on `custom_components/energy_optimizer/calculations/price_windows.py` while another works on registration and translation follow-up in `custom_components/energy_optimizer/sensor.py` and `custom_components/energy_optimizer/translations/en.json`.
3. Final quickstart validation can proceed once all implementation work is merged.

---

## Notes

- `[P]` tasks touch different files or can proceed independently after prerequisites are met.
- `[US1]`, `[US2]`, and `[US3]` map directly to the user stories in `spec.md` for traceability.
- The MVP is User Story 1.
- Focused validation should use the quickstart command set before broader suites.