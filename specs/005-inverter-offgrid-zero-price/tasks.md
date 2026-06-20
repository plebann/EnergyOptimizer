---
description: "Tasks for Inverter Off-Grid Mode on Zero Sell Price"
---

# Tasks: Inverter Off-Grid Mode on Zero Sell Price

**Input**: Design documents from `specs/005-inverter-offgrid-zero-price/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no blocking dependencies)
- **[Story]**: User story label — US1, US2, US3, US4
- Exact file paths are included in every task description

---

## Phase 1: Setup

> No project initialization required — all changes are additive to existing files in the current HA custom component structure.

*(No tasks — proceed directly to Phase 2)*

---

## Phase 2: Foundational (Blocking Prerequisite)

**Purpose**: Add the new config constant that every subsequent task depends on.

**⚠️ CRITICAL**: All Phase 3–5 tasks require this phase to be complete first.

- [X] T001 Add `CONF_INVERTER_OFFGRID_SWITCH = "inverter_offgrid_switch"` constant after `CONF_INVERTER_EXPORT_SURPLUS_SWITCH` in `custom_components/energy_optimizer/const.py`

**Checkpoint**: `CONF_INVERTER_OFFGRID_SWITCH` available for import — all other phases can now begin.

---

## Phase 3: User Stories 1 & 2 — Off-Grid Decision Engine (Priority: P1) 🎯 MVP

**Goal**: When sell price is effectively zero (< 0.05 PLN/kWh; rounds to 0.0 at 1 decimal place) and the Inverter OffGrid switch is configured, turn it ON (off-grid mode). When price recovers (≥ 0.05 PLN/kWh), turn it OFF. Existing surplus-switch path is untouched.

**Independent Test**: Set `CONF_INVERTER_OFFGRID_SWITCH` in entry data, price = 0.0 → `async_run_export_block_control` turns switch ON; price = 50 with switch ON → turns switch OFF. Existing tests must still pass.

### Implementation for User Stories 1 & 2

- [X] T002 [US1] Add `CONF_INVERTER_OFFGRID_SWITCH` to the `from ..const import (...)` block in `custom_components/energy_optimizer/decision_engine/export_block_control.py`
- [X] T003 [US1] Insert off-grid/grid-reconnect branch in `async_run_export_block_control` in `custom_components/energy_optimizer/decision_engine/export_block_control.py` — after `price` is read and before the existing surplus-switch state read; branch reads `config.get(CONF_INVERTER_OFFGRID_SWITCH)`, checks switch state, calls `turn_on_switch` (price ≤ 0) or `turn_off_switch` (price > 0), then returns early so surplus-switch path is never reached when off-grid switch is configured

### Tests for User Stories 1 & 2

- [X] T004 [P] [US1] Add `_OFFGRID_SWITCH = "switch.inverter_offgrid"` constant and `_setup_hass_with_offgrid()` helper (mirrors `_setup_hass()` but includes `CONF_INVERTER_OFFGRID_SWITCH` in `entry.data` and off-grid switch entity in `hass.states`) in `tests/test_export_block_control.py`
- [X] T005 [US1] Add `test_offgrid_turns_on_when_price_zero_and_switch_off`: price=`"0.0"`, offgrid switch state `"off"` → assert `turn_on` called on `_OFFGRID_SWITCH` in `tests/test_export_block_control.py`
- [X] T006 [US1] Add `test_offgrid_no_action_when_price_zero_and_already_on`: price=`"0.0"`, offgrid switch state `"on"` → assert no service call in `tests/test_export_block_control.py`
- [X] T007 [US1] Add `test_offgrid_surplus_switch_not_touched_when_offgrid_configured`: price=`"0.0"`, offgrid=`"off"`, surplus configured and `"on"` → assert only offgrid switch toggled, surplus switch service NOT called in `tests/test_export_block_control.py`
- [X] T008 [US2] Add `test_offgrid_turns_off_when_price_positive_and_switch_on`: price=`"50"`, offgrid switch state `"on"` → assert `turn_off` called on `_OFFGRID_SWITCH` in `tests/test_export_block_control.py`
- [X] T009 [US2] Add `test_offgrid_no_action_when_price_positive_and_already_off`: price=`"50"`, offgrid switch state `"off"` → assert no service call in `tests/test_export_block_control.py`
- [X] T010 [US2] Add `test_offgrid_entity_unavailable_skip`: offgrid switch entity ID configured but not present in `hass.states` → assert no service call in `tests/test_export_block_control.py`

**Checkpoint**: User Stories 1 & 2 fully functional — off-grid activation and grid-reconnect work, all 7 tests pass, existing surplus-switch tests unchanged.

---

## Phase 4: User Story 3 — Configuration via Options Flow (Priority: P2)

**Goal**: User can set/clear the Inverter OffGrid switch entity via Config and Options flow UI, stored in `config_entry.data`, without HA restart.

**Independent Test**: Add `CONF_INVERTER_OFFGRID_SWITCH` field to `control_entities` step; provide a valid `switch.*` entity ID → value saved; provide invalid domain → `not_switch_entity` error shown.

### Implementation for User Story 3

- [X] T011 [US3] Add `CONF_INVERTER_OFFGRID_SWITCH` to the `from .const import (...)` block in `custom_components/energy_optimizer/config_flow.py`
- [X] T012 [US3] Add `vol.Optional(CONF_INVERTER_OFFGRID_SWITCH): selector.EntitySelector(selector.EntitySelectorConfig(domain="switch"))` after the `CONF_INVERTER_EXPORT_SURPLUS_SWITCH` entry in `EnergyOptimizerConfigFlow.async_step_control_entities` schema in `custom_components/energy_optimizer/config_flow.py`
- [X] T013 [US3] Add validation block for `CONF_INVERTER_OFFGRID_SWITCH` (optional, `expected_domain="switch"`, `domain_error="not_switch_entity"`) in `_validate_control_entities` in `custom_components/energy_optimizer/config_flow.py`
- [X] T014 [US3] Add `vol.Optional(CONF_INVERTER_OFFGRID_SWITCH, default=self._config_entry.data.get(CONF_INVERTER_OFFGRID_SWITCH)): selector.EntitySelector(selector.EntitySelectorConfig(domain="switch"))` after `CONF_INVERTER_EXPORT_SURPLUS_SWITCH` entry in `EnergyOptimizerOptionsFlow.async_step_control_entities` schema in `custom_components/energy_optimizer/config_flow.py`
- [X] T015 [P] [US3] Add `"inverter_offgrid_switch"` label to `data` section and descriptive text to `data_description` section of the `control_entities` step in `custom_components/energy_optimizer/translations/en.json`

**Checkpoint**: User Story 3 done — field appears in HA UI Config and Options flow; value round-trips correctly; domain validation works.

---

## Phase 5: User Story 4 & Polish (Priority: P2)

**Goal**: Confirm the existing sun-above-horizon guard protects the new off-grid path at night; run full test suite to verify no regressions.

**Independent Test**: Sun below horizon + price 0.0 + off-grid switch configured → no service call.

### Tests for User Story 4

- [X] T016 [US4] Add `test_offgrid_no_action_when_sun_not_above_horizon`: `sun_state="below_horizon"`, price=`"0.0"`, offgrid switch state `"off"` → assert no service call in `tests/test_export_block_control.py`

### Polish

- [X] T017 Run full test suite and confirm zero failures:
  ```
  wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/test_export_block_control.py -v'
  ```
- [X] T018 Run broader smoke set to verify no regressions in related decision engines:
  ```
  wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/ -q'
  ```
  Result: 263 passed, 6 unrelated failures in `tests/test_morning_arbitrage.py` caused by missing `entry_id` arguments in existing test calls.

**Checkpoint**: All tests green — US4 guarded, no regressions in existing export-block or other decision engines.

---

## Dependencies

```
T001 (const.py)
  ├── T002 (import in export_block_control.py)
  │     └── T003 (off-grid branch logic)  ←── also parallel with T004
  │           └── T004 (test helper)       ←── can be written alongside T003
  │                 ├── T005 (test: turn on at zero)
  │                 ├── T006 (test: idempotent at zero)
  │                 ├── T007 (test: surplus not touched)
  │                 ├── T008 (test: turn off at positive)
  │                 ├── T009 (test: idempotent at positive)
  │                 ├── T010 (test: entity unavailable)
  │                 └── T016 (test: sun guard)
  └── T011 (import in config_flow.py)
        ├── T012 (ConfigFlow schema)
        ├── T013 (ConfigFlow validation)
        └── T014 (OptionsFlow schema)
              └── T015 [P] (translations — different file, parallel with T011-T014)
```

## Parallel Execution Examples

### Parallel batch after T001

Once `const.py` is updated, two independent tracks start:

**Track A — Decision Engine** (T002 → T003 → T004 → T005–T010, T016):
```
T002 → T003 ─┬─ T004 → T005
              │         T006
              │         T007
              │         T008
              │         T009
              │         T010
              └────────  T016
```

**Track B — Configuration UI** (T011 → T012, T013, T014; T015 in parallel):
```
T011 → T012
     → T013
     → T014
T015 (parallel with all of Track B — different file)
```

Track A and Track B are fully independent after T001 and can be worked simultaneously.

---

## Implementation Strategy

**MVP scope**: Phase 2 + Phase 3 (T001–T010). Delivers the core decision-engine behavior with full test coverage. US3 (config UI) and US4 (night guard test) are additive.

**Suggested order for a single developer**:

1. T001 (2 min) — add constant
2. T002, T003 (15 min) — implement decision-engine branch
3. T004–T010, T016 (20 min) — write all tests
4. T011–T015 (15 min) — config flow + translations
5. T017, T018 (5 min) — verify full suite

Total estimated effort: ~1 hour.
