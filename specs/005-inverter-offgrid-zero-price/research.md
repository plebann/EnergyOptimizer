# Research: Inverter Off-Grid Mode on Zero Sell Price

**Feature**: `005-inverter-offgrid-zero-price`
**Date**: 2026-06-20

## Decision 1: Zero-price threshold reuse

**Decision**: Reuse the existing `ZERO_PRICE_THRESHOLD = 0.05` constant from `custom_components/energy_optimizer/calculations/price_windows.py`.

**Rationale**: The same threshold is already used to determine when sell prices are "effectively zero" across the integration. Reusing it ensures behavioral consistency — the same price level that triggers other zero-price decisions will also trigger off-grid mode. No new constant or configuration knob is introduced.

**Alternatives considered**: Introducing a separate configurable threshold for off-grid switching. Rejected: over-engineering for no clear benefit; the existing threshold is already appropriate and user-configurable behavior is not required.

---

## Decision 2: Off-grid switch control pattern

**Decision**: Reuse `turn_on_switch` / `turn_off_switch` from `controllers/inverter.py`, passing `entry`, `logger`, and `Context()` exactly as the existing export-surplus-switch path does.

**Rationale**: The inverter controller abstraction already handles test-mode guards and service-call logging uniformly. Using it for the new off-grid switch avoids duplicating service-call code and benefits from test-mode suppression automatically.

**Alternatives considered**: Calling `hass.services.async_call` directly. Rejected: bypasses test-mode guard and duplicates boilerplate.

---

## Decision 3: Mutual exclusivity — off-grid vs. export-surplus

**Decision**: When `CONF_INVERTER_OFFGRID_SWITCH` is configured, the entire off-grid path runs and the export-surplus path is skipped (early return). When it is not configured, existing export-surplus behavior runs unchanged.

**Rationale**: The two behaviors are alternatives for the same trigger (zero price). Allowing both to run simultaneously would cause undefined state and complicate observability. Priority of off-grid over surplus is per-spec: off-grid is the newer, stronger response.

**Alternatives considered**: Running both switches in sequence (off-grid then surplus). Rejected: could confuse inverter state and violates spec FR-003.

---

## Decision 4: Config entry schema — no VERSION bump required

**Decision**: `CONF_INVERTER_OFFGRID_SWITCH` is added as a new optional key. No `VERSION` bump, no `async_migrate_entry` change.

**Rationale**: The constitution states `VERSION` MUST only be bumped for backward-incompatible schema changes (removed keys, renamed keys, type changes). Adding an optional key read via `.get()` with default `None` is backward-compatible: existing entries without the key will naturally get `None`, meaning the feature is disabled, which is the correct default.

**Alternatives considered**: Bumping `MINOR_VERSION`. Rejected: `MINOR_VERSION` is not present in this codebase (no `MINOR_VERSION` attribute in config_flow.py or `__init__.py`).

---

## Decision 5: Field placement in config/options flow

**Decision**: Add `CONF_INVERTER_OFFGRID_SWITCH` to the `control_entities` step in both `EnergyOptimizerConfigFlow` and `EnergyOptimizerOptionsFlow`, adjacent to `CONF_INVERTER_EXPORT_SURPLUS_SWITCH`.

**Rationale**: Both switches are inverter control switches. Grouping them in the same step maintains UI coherence and follows the pattern established by `CONF_INVERTER_EXPORT_SURPLUS_SWITCH`. Validation mirrors the existing surplus-switch validation (optional, must be a `switch` domain entity if provided).

**Alternatives considered**: Separate config step for off-grid settings. Rejected: unnecessary complexity for a single optional field.

---

## Decision 6: Translations — English only

**Decision**: Add labels only to `translations/en.json`. No other language files exist in the integration.

**Rationale**: Only `en.json` is present in `custom_components/energy_optimizer/translations/`. There is no `pl.json` or other locale.

---

## Decision 7: Test strategy

**Decision**: Add new test cases to `tests/test_export_block_control.py` alongside existing tests. No existing test cases are modified.

**New test cases**:
1. Off-grid switch turns ON when price ≤ 0, switch currently OFF.
2. Off-grid switch turns OFF when price > 0, switch currently ON.
3. No service call when price ≤ 0 and off-grid switch already ON (idempotent).
4. No service call when price > 0 and off-grid switch already OFF (idempotent).
5. Export surplus switch NOT called when off-grid switch is configured and price ≤ 0.
6. Sun-below-horizon guard: no change when off-grid switch configured.
7. Backward-compat: off-grid switch not configured → existing surplus-switch behavior unchanged.

**Rationale**: Additive test approach preserves all regression coverage. New tests are written as isolated async tests using the existing `_setup_hass` mock pattern.
