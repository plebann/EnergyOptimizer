# Tasks: Cztery Sensory Optymalnych Okien Sprzedazy Energii

**Input**: Design documents from `/specs/003-sell-window-sensors/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/sell-window-sensors.md`, `quickstart.md`

**Tests**: Test tasks are REQUIRED because this feature changes a pricing decision path, extends the published sensor surface, and adds ranking, tie-break, rounding, degradation, and coexistence rules.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare shared test and translation surfaces used by all stories.

- [X] T001 Prepare ranked sell-window fixture helpers in `tests/test_price_windows.py`
- [X] T002 [P] Prepare ranked pricing sensor fixture helpers in `tests/test_pricing_sensors.py`
- [X] T003 [P] Add placeholder translation keys for ranked sell-window sensors in `custom_components/energy_optimizer/translations/en.json`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the shared ranking and entity plumbing required before any user story can be implemented.

**⚠️ CRITICAL**: No user story work should begin until this phase is complete.

- [X] T004 Refactor hourly sell-price parsing, `prices_today`/`prices_tomorrow` payload selection, range constants, and ranking result types in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T005 Implement full-hour candidate filtering, out-of-range record exclusion, and day/range slice helper behavior in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T006 Implement shared ranked sell-window sensor base behavior in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T007 [P] Export ranked sell-window sensor classes alongside existing midday sensors in `custom_components/energy_optimizer/entities/sensors/__init__.py`
- [X] T008 [P] Prepare ranked sell-window sensor registration slots without removing existing sensors in `custom_components/energy_optimizer/sensor.py`
- [X] T009 Define translation-backed sensor identity using `translation_key` and config-entry-scoped `unique_id` values for ranked sell-window sensors in `custom_components/energy_optimizer/entities/sensors/pricing.py`

**Checkpoint**: Foundation ready - user story implementation can now begin.

---

## Phase 3: User Story 1 - Dzisiejsze okna sprzedazy (Priority: P1) 🎯 MVP

**Goal**: Publish today morning and today evening ranked sell-window sensors with the best-window start time and runner-up comparison attributes.

**Independent Test**: With complete `prices_today` data, the integration publishes two today sensors whose states are `HH:MM` and whose attributes expose `price`, `second_window_start`, `second_window_price`, and `second_window_gap_pct` with the required rounding.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T010 [P] [US1] Add today morning and evening ranking, full-hour filtering, and rounding tests in `tests/test_price_windows.py`
- [X] T011 [P] [US1] Add today morning and evening sensor publication tests, including minimal `translation_key` and config-entry-scoped `unique_id` identity checks plus one assertion that existing midday sensors remain unchanged, in `tests/test_pricing_sensors.py`

### Implementation for User Story 1

- [X] T012 [US1] Implement today morning and evening candidate selection and ranking output shaping in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T013 [US1] Implement today morning and evening ranked sensor entities with `second_window_*` attributes in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T014 [US1] Register today ranked sell-window sensors in `custom_components/energy_optimizer/sensor.py`
- [X] T015 [US1] Finalize today ranked sell-window translations in `custom_components/energy_optimizer/translations/en.json`

**Checkpoint**: User Story 1 should now expose both today ranked sensors and be independently testable.

---

## Phase 4: User Story 2 - Jutrzejsze okna sprzedazy (Priority: P2)

**Goal**: Publish tomorrow morning and tomorrow evening ranked sell-window sensors using only `prices_tomorrow` data.

**Independent Test**: With complete `prices_tomorrow` data, the integration publishes two tomorrow sensors with the same `HH:MM` state contract and ranked attributes, without affecting today sensors or the pre-existing sensor set.

### Tests for User Story 2

- [X] T016 [P] [US2] Add tomorrow day-scoping and payload-isolation ranking tests in `tests/test_price_windows.py`
- [X] T017 [P] [US2] Add tomorrow morning and evening sensor publication isolation tests, including minimal `translation_key` and config-entry-scoped `unique_id` identity checks plus one assertion that existing midday sensors remain unchanged, in `tests/test_pricing_sensors.py`

### Implementation for User Story 2

- [X] T018 [US2] Implement tomorrow payload selection and day-offset handling in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T019 [US2] Implement tomorrow morning and evening ranked sensor entities in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T020 [US2] Register tomorrow ranked sell-window sensors in `custom_components/energy_optimizer/sensor.py`
- [X] T021 [US2] Finalize tomorrow ranked sell-window translations in `custom_components/energy_optimizer/translations/en.json`

**Checkpoint**: User Stories 1 and 2 should now expose four ranked sensors across both days.

---

## Phase 5: User Story 3 - Przewidywalny ranking bez regresji (Priority: P3)

**Goal**: Enforce deterministic tie-breaking, strict top-two availability rules, invalid-data rejection, safe percentage omission for zero-valued best windows, and no regressions in existing sensors.

**Independent Test**: With tied prices, missing candidates, invalid or duplicate hourly records, out-of-range records, or a best price of zero, the shared ranking logic and published entities still produce deterministic results, ignore irrelevant records, and never publish misleading partial output, while existing sensors remain present and unchanged.

### Tests for User Story 3

- [X] T022 [P] [US3] Add tie-break, out-of-range exclusion, missing-runner-up, invalid-time, invalid-price, duplicate-hour, and zero-best-price gap omission tests in `tests/test_price_windows.py`
- [X] T023 [P] [US3] Add slice-local unavailable-state, buy-price-invariance, existing-sensor regression, and broader sensor identity regression coverage for `translation_key` and config-entry-scoped `unique_id` in `tests/test_pricing_sensors.py`
- [X] T024 [P] [US3] Add sensor-registration coexistence regression coverage in `tests/test_services_registration.py`

### Implementation for User Story 3

- [X] T025 [US3] Enforce earliest-start tie-breaking, duplicate/invalid record rejection, out-of-range exclusion, and top-two availability rules in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T026 [US3] Apply slice-local unavailable-state and `second_window_gap_pct` omission behavior in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T027 [US3] Verify existing sensor registration remains unchanged while ranked sensors are additive in `custom_components/energy_optimizer/sensor.py`

**Checkpoint**: All ranked sensor variants should now behave deterministically across edge cases and coexist cleanly with the existing sensors.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and documentation alignment across the completed feature.

- [X] T028 [P] Review `specs/003-sell-window-sensors/contracts/sell-window-sensors.md` and `specs/003-sell-window-sensors/quickstart.md` for final terminology alignment with implemented behavior
- [X] T029 [P] Validate that feature 003 remains sell-only by confirming no buy-window logic, translation keys, entities, or tests were added in `custom_components/energy_optimizer/calculations/price_windows.py`, `custom_components/energy_optimizer/translations/en.json`, `custom_components/energy_optimizer/entities/sensors/pricing.py`, `custom_components/energy_optimizer/sensor.py`, `tests/test_price_windows.py`, and `tests/test_pricing_sensors.py`
- [X] T030 Run focused validation from `specs/003-sell-window-sensors/quickstart.md` with `tests/test_price_windows.py`, `tests/test_pricing_sensors.py`, and `tests/test_services_registration.py`

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

- `T002` and `T003` can run in parallel after `T001` begins the shared scaffolding.
- `T007` and `T008` can run in parallel after `T006` defines the ranked sensor base shape.
- `T010` and `T011` can run in parallel for User Story 1.
- `T016` and `T017` can run in parallel for User Story 2.
- `T022`, `T023`, and `T024` can run in parallel for User Story 3.
- `T028` and `T029` can run in parallel once implementation is complete.

---

## Parallel Example: User Story 1

```bash
# Launch the today-specific tests together first
Task: "Add today morning and evening ranking, full-hour filtering, and rounding tests in tests/test_price_windows.py"
Task: "Add today morning and evening sensor publication tests, including minimal identity checks and one unchanged-existing-sensor assertion, in tests/test_pricing_sensors.py"
```

## Parallel Example: User Story 2

```bash
# Validate tomorrow behavior and day isolation in parallel
Task: "Add tomorrow day-scoping and payload-isolation ranking tests in tests/test_price_windows.py"
Task: "Add tomorrow morning and evening sensor publication isolation tests, including minimal identity checks and one unchanged-existing-sensor assertion, in tests/test_pricing_sensors.py"
```

## Parallel Example: User Story 3

```bash
# Harden ranking edge cases and coexistence in parallel
Task: "Add tie-break, out-of-range exclusion, missing-runner-up, invalid-time, invalid-price, duplicate-hour, and zero-best-price gap omission tests in tests/test_price_windows.py"
Task: "Add slice-local unavailable-state, buy-price-invariance, existing-sensor regression, and broader sensor identity regression coverage in tests/test_pricing_sensors.py"
Task: "Add sensor-registration coexistence regression coverage in tests/test_services_registration.py"
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
3. Coexistence and registration regression coverage in `tests/test_services_registration.py` can be owned separately during User Story 3.
4. Final quickstart validation can proceed once all implementation work is merged.

---

## Notes

- `[P]` tasks touch different files or can proceed independently after prerequisites are met.
- `[US1]`, `[US2]`, and `[US3]` map directly to the user stories in `spec.md` for traceability.
- The MVP is User Story 1.
- Focused validation should use the quickstart command set before broader suites.