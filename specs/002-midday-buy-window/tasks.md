# Tasks: Rozszerzenie Sensorów Okna Najniższej Ceny Zakupu

**Input**: Design documents from `/specs/002-midday-buy-window/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/midday-buy-window-sensor.md`, `quickstart.md`

**Tests**: Test tasks are REQUIRED because this feature extends a decision path with quasi-zero precedence, day-scoped payload selection, `price`, `is_active`, tie-breaking, and `unavailable` behavior across two derived sensors.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare the buy-window file surfaces, shared fixtures, and translation placeholders used by all stories.

- [X] T001 Prepare midday buy-window calculation fixtures in `tests/test_price_windows.py`
- [X] T002 [P] Prepare midday buy-window sensor fixtures in `tests/test_pricing_sensors.py`
- [X] T003 [P] Add translation placeholders and sensor exports for midday buy-window variants in `custom_components/energy_optimizer/translations/en.json` and `custom_components/energy_optimizer/entities/sensors/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the shared calculation and entity plumbing required before any user story can be implemented.

**⚠️ CRITICAL**: No user story work should start before this phase is complete.

- [X] T004 Extend shared coordinator payload access for buy-price snapshots used by the midday buy-window sensors in `custom_components/energy_optimizer/coordinator.py`
- [X] T005 [P] Build the shared midday buy-window result contract and hourly normalization helpers in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T006 Implement the shared today/tomorrow midday buy-window base sensor behavior in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T007 [P] Wire additive midday buy-window sensor registration in `custom_components/energy_optimizer/sensor.py` and `custom_components/energy_optimizer/entities/sensors/__init__.py`

**Checkpoint**: Foundation ready — the feature can now be delivered story by story.

---

## Phase 3: User Story 1 - Odczyt najtańszego okna zakupu z ceną średnią i statusem aktywności (Priority: P1) 🎯 MVP

**Goal**: Keep the current-day midday buy-window sensor while adding `price` and `is_active` for a correctly selected current-day result.

**Independent Test**: With complete `prices_today` buy-price data and no quasi-zero entries, the current-day sensor publishes the expected `HH:MM-HH:MM` window, rounded `price`, and `is_active` set to `on` or `off` depending on the current local time.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T008 [P] [US1] Add current-day midday buy-window selection and average-price tests in `tests/test_price_windows.py`
- [X] T009 [P] [US1] Add current-day sensor state, `price`, and `is_active` tests in `tests/test_pricing_sensors.py`

### Implementation for User Story 1

- [X] T010 [US1] Implement current-day midday buy-window selection from `prices_today` in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T011 [US1] Implement current-day midday buy-window sensor publication with `price` and `is_active` in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T012 [US1] Finalize current-day translation-backed metadata and registration in `custom_components/energy_optimizer/translations/en.json` and `custom_components/energy_optimizer/sensor.py`

**Checkpoint**: User Story 1 now publishes the current-day midday buy-window with `price` and `is_active`.

---

## Phase 4: User Story 2 - Priorytetowe objęcie wszystkich zerowych cen zakupu (Priority: P2)

**Goal**: When zero or quasi-zero prices occur, publish the full span from the first to the last such occurrence instead of the standard 8-quarter-hour minimum window.

**Independent Test**: If at least one hourly buy-price entry in the evaluated day is below `0.05 PLN/kWh`, the published midday buy-window covers the entire span from the first to the last quasi-zero occurrence and still exposes the correct rounded average `price`.

### Tests for User Story 2

- [X] T013 [P] [US2] Add quasi-zero precedence and full-span selection tests in `tests/test_price_windows.py`
- [X] T014 [P] [US2] Add sensor publication tests covering quasi-zero spans and `is_active` interaction in `tests/test_pricing_sensors.py`

### Implementation for User Story 2

- [X] T015 [US2] Implement quasi-zero span selection with precedence over the standard selector in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T016 [US2] Ensure current-day sensor publication reflects the quasi-zero result contract in `custom_components/energy_optimizer/entities/sensors/pricing.py`

**Checkpoint**: Quasi-zero buy-price days now override the standard midday window selection path.

---

## Phase 5: User Story 3 - Odczyt analogicznego okna dla jutra (Priority: P3)

**Goal**: Publish an analogous tomorrow sensor that uses only `prices_tomorrow`, publishes `price`, and omits `is_active`.

**Independent Test**: With complete `prices_tomorrow` buy-price data, the integration publishes a separate tomorrow sensor with the correct `HH:MM-HH:MM` window and rounded `price`, while never publishing `is_active` for tomorrow.

### Tests for User Story 3

- [X] T017 [P] [US3] Add tomorrow-payload selection and day-isolation tests in `tests/test_price_windows.py`
- [X] T018 [P] [US3] Add tomorrow sensor publication tests for state, `price`, and omitted `is_active` in `tests/test_pricing_sensors.py`

### Implementation for User Story 3

- [X] T019 [US3] Generalize the midday buy-window selector for `prices_tomorrow` and day-scoped evaluation in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T020 [US3] Implement the tomorrow midday buy-window sensor in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T021 [US3] Register the tomorrow sensor and translation-backed metadata in `custom_components/energy_optimizer/sensor.py` and `custom_components/energy_optimizer/translations/en.json`

**Checkpoint**: User Stories 1-3 now expose both today and tomorrow midday buy-window sensors with day-specific attribute contracts.

---

## Phase 6: User Story 4 - Zachowanie bez zmian poza nowymi atrybutami informacyjnymi i regułą zerowych cen (Priority: P4)

**Goal**: Preserve deterministic earliest-start fallback, isolate failures to the affected day, and omit dependent attributes when no valid window exists.

**Independent Test**: With incomplete, invalid, or sparse data, only the affected day sensor becomes `unavailable`; `price` and `is_active` are omitted on unavailable results; and days without quasi-zero prices preserve the previous cheapest-window and earliest-tie behavior.

### Tests for User Story 4

- [X] T022 [P] [US4] Add insufficient-data, earliest-tie, and unavailable-result tests in `tests/test_price_windows.py`
- [X] T023 [P] [US4] Add entity regression tests for unavailable sensors, omitted attributes, and buy-price-only behavior in `tests/test_pricing_sensors.py`
- [X] T024 [P] [US4] Add explicit tomorrow-no-`is_active` boundary tests in `tests/test_pricing_sensors.py`

### Implementation for User Story 4

- [X] T025 [US4] Preserve earliest-start fallback for standard windows when no quasi-zero prices exist in `custom_components/energy_optimizer/calculations/price_windows.py`
- [X] T026 [US4] Omit `price` and `is_active` on unavailable results and keep `is_active` today-only in `custom_components/energy_optimizer/entities/sensors/pricing.py`
- [X] T027 [US4] Preserve additive coexistence with the rest of the pricing sensor set in `custom_components/energy_optimizer/entities/sensors/__init__.py` and `custom_components/energy_optimizer/sensor.py`

**Checkpoint**: The full feature behaves deterministically across normal, quasi-zero, tomorrow, and failure-mode scenarios.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final artifact alignment and focused validation across the completed feature.

- [X] T028 [P] Align `specs/002-midday-buy-window/quickstart.md` with the final today/tomorrow buy-window behavior
- [X] T029 [P] Align `specs/002-midday-buy-window/contracts/midday-buy-window-sensor.md` with `price`, `is_active`, and quasi-zero precedence
- [X] T030 Run focused validation from `specs/002-midday-buy-window/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1: Setup**: No dependencies — can start immediately.
- **Phase 2: Foundational**: Depends on Phase 1 and blocks all user stories.
- **Phase 3: User Story 1**: Depends on Phase 2 completion.
- **Phase 4: User Story 2**: Depends on Phase 2 and hardens the shared selector used by US1.
- **Phase 5: User Story 3**: Depends on Phase 2 and reuses the shared selector plus entity base built earlier.
- **Phase 6: User Story 4**: Depends on the core today/tomorrow behavior from US1-US3.
- **Phase 7: Polish**: Depends on all desired user stories being complete.

### User Story Dependencies

- **User Story 1 (P1)**: MVP and first deliverable after the foundational phase.
- **User Story 2 (P2)**: Can start after the foundational phase but refines the shared selection rules used by all midday buy-window outputs.
- **User Story 3 (P3)**: Can start after the foundational phase and should remain independently testable through tomorrow-only scenarios.
- **User Story 4 (P4)**: Builds on the completed behavior from the earlier stories to validate degradation and stability guarantees.

### Within Each User Story

- Tests MUST be written and fail before implementation changes.
- Shared calculation behavior must land before entity publication depends on it.
- Entity logic must be in place before translation and registration finalization.
- Story-level validation should run before moving to the next priority.

### Parallel Opportunities

- `T002` and `T003` can run in parallel after `T001` begins the shared scaffolding.
- `T005` and `T006` can run in parallel once coordinator payload access is defined.
- `T008` and `T009` can run in parallel for US1.
- `T013` and `T014` can run in parallel for US2.
- `T017` and `T018` can run in parallel for US3.
- `T022`, `T023`, and `T024` can run in parallel for US4.
- `T028` and `T029` can run in parallel once implementation is complete.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational.
3. Complete Phase 3: User Story 1.
4. Stop and validate the current-day midday buy-window sensor with `price` and `is_active`.

### Incremental Delivery

1. Deliver US1 to extend today’s sensor with `price` and `is_active`.
2. Deliver US2 to add the quasi-zero precedence rule.
3. Deliver US3 to add the tomorrow sensor with its day-specific contract.
4. Deliver US4 to harden unavailable behavior, day isolation, and regression guarantees.
5. Finish with artifact sync and focused validation.

### Parallel Team Strategy

1. One developer can focus on shared calculation behavior in `custom_components/energy_optimizer/calculations/price_windows.py` while another prepares entity-level tests in `tests/test_pricing_sensors.py`.
2. Translation and registration work can proceed in parallel once the shared sensor contracts are stable.
3. Final artifact synchronization can proceed in parallel with focused validation after the code behavior is locked.

---

## Notes

- `[P]` tasks touch different files or can proceed independently after prerequisites are complete.
- Story labels map directly to the user stories in `spec.md` for traceability.
- The MVP is User Story 1.
- Focused validation should prefer the quickstart command set before broader suites.
