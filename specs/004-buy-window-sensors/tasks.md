# Tasks: Cztery Sensory Optymalnych Okien Zakupu Energii

**Input**: Design documents from `/specs/004-buy-window-sensors/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/buy-window-sensors.md`, `quickstart.md`

**Tests**: Test tasks are REQUIRED because this feature adds a pricing decision path, deterministic tie-break rules, controlled degradation rules, and four new published sensor entities.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare shared fixtures, translation placeholders, and file targets used by all user stories.

- [X] T001 Prepare buy-window calculation fixture helpers in `tests/test_price_windows.py`
- [X] T002 [P] Prepare buy-window pricing sensor fixture helpers in `tests/test_pricing_sensors.py`
- [X] T003 [P] Add placeholder translation keys for buy-window sensors in `custom_components/energy_optimizer/translations/en.json`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the shared calculation and entity plumbing required before any user story can be implemented.

**⚠️ CRITICAL**: No user story work should begin until this phase is complete.

- [X] T004 Refactor buy-price payload parsing, shared result types, and hourly normalization helpers in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T005 Implement shared two-hour candidate building and range-filtering helpers in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T006 Implement shared buy-window base sensor behavior with translation-backed identity in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T007 [P] Export buy-window sensor classes in `custom_components/energy_optimizer/entities/sensors/__init__.py`
- [X] T008 [P] Prepare additive buy-window sensor registration slots in `custom_components/energy_optimizer/sensor.py`

**Checkpoint**: Foundation ready - user story implementation can now begin.

---

## Phase 3: User Story 1 - Dzisiejsze okna zakupu dzien i noc (Priority: P1) 🎯 MVP

**Goal**: Publish today night and today day buy-window sensors with `HH:MM` state, rounded `price`, and `is_negative` attributes.

**Independent Test**: With complete `prices_today` data, the integration publishes two today sensors whose states are `HH:MM` and whose attributes expose `price` and `is_negative` with the required semantics.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T009 [P] [US1] Add today night and day candidate-selection tests in `tests/test_price_windows.py`
- [X] T010 [P] [US1] Add today buy-window sensor state and attribute tests in `tests/test_pricing_sensors.py`

### Implementation for User Story 1

- [X] T011 [US1] Implement today night and day buy-window selection in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T012 [US1] Implement today night and day buy-window sensor classes in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T013 [US1] Register today buy-window sensors in `custom_components/energy_optimizer/sensor.py`
- [X] T014 [US1] Finalize today buy-window translations in `custom_components/energy_optimizer/translations/en.json`

**Checkpoint**: User Story 1 should now expose both today buy-window sensors and be independently testable.

---

## Phase 4: User Story 2 - Jutrzejsze okna zakupu dzien i noc (Priority: P2)

**Goal**: Publish tomorrow night and tomorrow day buy-window sensors using only `prices_tomorrow` data.

**Independent Test**: With complete `prices_tomorrow` data, the integration publishes two tomorrow sensors with the same `HH:MM` state contract and the same attributes, without affecting today sensors.

### Tests for User Story 2

- [X] T015 [P] [US2] Add tomorrow payload-isolation and empty-`prices_tomorrow` tests in `tests/test_price_windows.py`
- [X] T016 [P] [US2] Add tomorrow buy-window sensor publication and unavailable-state tests in `tests/test_pricing_sensors.py`

### Implementation for User Story 2

- [X] T017 [US2] Implement tomorrow payload selection and empty-list handling in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T018 [US2] Implement tomorrow night and day buy-window sensor classes in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T019 [US2] Register tomorrow buy-window sensors in `custom_components/energy_optimizer/sensor.py`
- [X] T020 [US2] Finalize tomorrow buy-window translations in `custom_components/energy_optimizer/translations/en.json`

**Checkpoint**: User Stories 1 and 2 should now expose four buy-window sensors across both days.

---

## Phase 5: User Story 3 - Przewidywalny wybor i bezpieczne zachowanie graniczne (Priority: P3)

**Goal**: Enforce deterministic tie-breaking, strict invalid-data rejection, negative-price signaling, and additive coexistence with existing sensors.

**Independent Test**: With tied prices, non-full-hour records, missing or invalid hourly data, negative averages, and sparse day slices, the new sensors still produce deterministic results or become `unavailable` without affecting unrelated sensors.

### Tests for User Story 3

- [X] T021 [P] [US3] Add tie-break, invalid-record, non-full-hour, and negative-average tests in `tests/test_price_windows.py`
- [X] T022 [P] [US3] Add slice-local unavailable, `is_negative`, and identity/coexistence tests in `tests/test_pricing_sensors.py`
- [X] T023 [P] [US3] Add explicit `price == 0` -> `is_negative == false` boundary tests in `tests/test_price_windows.py` and `tests/test_pricing_sensors.py`
- [X] T024 [P] [US3] Add explicit unchanged-existing-sensor behavior regression tests in `tests/test_pricing_sensors.py`
- [X] T025 [P] [US3] Add additive sensor-registration regression coverage in `tests/test_services_registration.py`

### Implementation for User Story 3

- [X] T026 [US3] Enforce night/day tie-break ordering and invalid-candidate rejection in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T027 [US3] Apply unavailable attribute omission and `is_negative` publication rules in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T028 [US3] Preserve additive sensor exports for new and existing pricing sensors in `custom_components/energy_optimizer/entities/sensors/__init__.py`

**Checkpoint**: All buy-window sensor variants should now behave deterministically across edge cases and coexist cleanly with the existing sensor set.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and documentation alignment across the completed feature.

- [X] T029 [P] Align `specs/004-buy-window-sensors/quickstart.md` with final entity names and validation commands in `specs/004-buy-window-sensors/quickstart.md`
- [X] T030 [P] Align final output semantics in `specs/004-buy-window-sensors/contracts/buy-window-sensors.md`
- [X] T031 Run focused validation from `specs/004-buy-window-sensors/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion - blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational completion.
- **User Story 2 (Phase 4)**: Depends on Foundational completion.
- **User Story 3 (Phase 5)**: Depends on Foundational completion and hardens the shared behavior used by all sensor variants.
- **Polish (Phase 6)**: Depends on all desired user stories being complete.

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational completion - MVP and no dependency on other stories.
- **User Story 2 (P2)**: Can start after Foundational completion - should remain independently testable even though it reuses the same shared calculation and sensor files.
- **User Story 3 (P3)**: Can start after Foundational completion - should remain independently testable through edge-case and regression scenarios on the shared contract.

### Within Each User Story

- Tests MUST be written and fail before implementation.
- Calculation-layer changes should land before entity publication depends on them.
- Entity publication should land before registration and translation finalization.
- Story-specific validation should run before moving to the next priority.

### Parallel Opportunities

- `T002` and `T003` can run in parallel after `T001` begins the shared scaffolding.
- `T007` and `T008` can run in parallel after `T006` defines the shared buy-window sensor shape.
- `T009` and `T010` can run in parallel for User Story 1.
- `T015` and `T016` can run in parallel for User Story 2.
- `T021`, `T022`, `T023`, `T024`, and `T025` can run in parallel for User Story 3.
- `T029` and `T030` can run in parallel once implementation is complete.

---

## Parallel Example: User Story 1

```bash
# Launch the today-specific tests together first
Task: "Add today night and day candidate-selection tests in tests/test_price_windows.py"
Task: "Add today buy-window sensor state and attribute tests in tests/test_pricing_sensors.py"
```

## Parallel Example: User Story 2

```bash
# Validate tomorrow behavior and empty-payload handling in parallel
Task: "Add tomorrow payload-isolation and empty-prices_tomorrow tests in tests/test_price_windows.py"
Task: "Add tomorrow buy-window sensor publication and unavailable-state tests in tests/test_pricing_sensors.py"
```

## Parallel Example: User Story 3

```bash
# Harden tie-breaks, degradation, and additive registration in parallel
Task: "Add tie-break, invalid-record, non-full-hour, and negative-average tests in tests/test_price_windows.py"
Task: "Add slice-local unavailable, is_negative, and identity/coexistence tests in tests/test_pricing_sensors.py"
Task: "Add explicit price == 0 -> is_negative == false boundary tests in tests/test_price_windows.py and tests/test_pricing_sensors.py"
Task: "Add explicit unchanged-existing-sensor behavior regression tests in tests/test_pricing_sensors.py"
Task: "Add additive sensor-registration regression coverage in tests/test_services_registration.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational.
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: Confirm the two today buy-window sensors work independently with `prices_today`.

### Incremental Delivery

1. Complete Setup + Foundational.
2. Deliver User Story 1 and validate today-only behavior.
3. Deliver User Story 2 and validate tomorrow isolation and empty-payload fallback.
4. Deliver User Story 3 and validate edge cases plus coexistence behavior.
5. Finish with focused regression validation.

### Parallel Team Strategy

1. One developer can prepare ranking fixtures in `tests/test_price_windows.py` while another prepares entity fixtures in `tests/test_pricing_sensors.py`.
2. After Foundational completion, one developer can focus on `custom_components/energy_optimizer/calculations/price_windows.py` while another handles registration and translation follow-up in `custom_components/energy_optimizer/sensor.py` and `custom_components/energy_optimizer/translations/en.json`.
3. Coexistence and registration regression coverage in `tests/test_services_registration.py` can be owned separately during User Story 3.
4. Final quickstart validation can proceed once all implementation work is merged.

---

## Notes

- `[P]` tasks touch different files or can proceed independently after prerequisites are met.
- `[US1]`, `[US2]`, and `[US3]` map directly to the user stories in `spec.md` for traceability.
- The MVP is User Story 1.
- Focused validation should use the quickstart command set before broader suites.