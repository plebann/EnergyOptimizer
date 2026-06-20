# Data Model: Inverter Off-Grid Mode on Zero Sell Price

**Feature**: `005-inverter-offgrid-zero-price`
**Date**: 2026-06-20

## New Config Key

### `CONF_INVERTER_OFFGRID_SWITCH`

| Attribute | Value |
|-----------|-------|
| Constant name | `CONF_INVERTER_OFFGRID_SWITCH` |
| String key | `"inverter_offgrid_switch"` |
| Type | `str \| None` |
| Default | `None` (feature disabled) |
| Storage | `config_entry.data` (same as all other control entities) |
| Config step | `control_entities` (both ConfigFlow and OptionsFlow) |
| Validation | Optional; when provided, entity must exist in `switch` domain |

**Semantics**: Entity ID of a HA switch entity representing the inverter's grid-connection state.

- `state == "off"` → inverter is grid-connected (normal operation)
- `state == "on"` → inverter is disconnected from grid (off-grid / island mode)

---

## Modified Logic: `export_block_control.async_run_export_block_control`

### Existing flow (unchanged when `CONF_INVERTER_OFFGRID_SWITCH` is `None`)

```
sun check → price read → surplus_switch state → toggle if needed
```

### New flow (when `CONF_INVERTER_OFFGRID_SWITCH` is configured)

```
sun check
  → price read
    → price ≤ ZERO_PRICE_THRESHOLD?
        YES → offgrid_switch already ON? → no-op
               offgrid_switch OFF?       → turn_on_switch(offgrid_switch) → return
        NO  → offgrid_switch already OFF? → no-op
               offgrid_switch ON?         → turn_off_switch(offgrid_switch) → return
```

The export-surplus-switch path is **never reached** when `CONF_INVERTER_OFFGRID_SWITCH` is configured.

### State transition table

| Price | Off-Grid Switch State | Action | Notes |
|-------|-----------------------|--------|-------|
| < 0.05 | off | turn_on (off-grid) | rounds to 0.0 at 1dp |
| < 0.05 | on  | no-op | already off-grid |
| ≥ 0.05 | on  | turn_off (grid reconnect) | price recovered |
| ≥ 0.05 | off | no-op | already grid-connected |
| any | n/a | fallback to surplus path | when offgrid switch not configured |

---

## Files Changed

| File | Change |
|------|--------|
| `const.py` | Add `CONF_INVERTER_OFFGRID_SWITCH = "inverter_offgrid_switch"` |
| `config_flow.py` | Add field to `async_step_control_entities` (ConfigFlow) + `async_step_control_entities` (OptionsFlow) + `_validate_control_entities` |
| `decision_engine/export_block_control.py` | Add off-grid branch before surplus-switch logic |
| `translations/en.json` | Add labels for `inverter_offgrid_switch` in `control_entities` step |
| `tests/test_export_block_control.py` | Add 7 new test cases; no existing tests changed |

---

## No Schema Migration Required

Adding an optional key read via `.get(CONF_INVERTER_OFFGRID_SWITCH)` is backward-compatible. Existing config entries without the key will return `None`, correctly disabling the feature. `VERSION` and `MINOR_VERSION` are not changed.
