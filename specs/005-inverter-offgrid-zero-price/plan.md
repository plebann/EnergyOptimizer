# Implementation Plan: Inverter Off-Grid Mode on Zero Sell Price

**Branch**: `main` | **Date**: 2026-06-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-inverter-offgrid-zero-price/spec.md`

## Summary

When the sell price is effectively zero (rounds to 0.0 at 1 decimal place; price < 0.05 PLN/kWh), the integration switches the inverter to off-grid mode (turn ON the Inverter OffGrid switch) instead of activating the export-surplus power limit. When prices recover, the inverter returns to grid-connected mode automatically. The feature is backward-compatible and opt-in via a new optional config entry key.

## Technical Context

**Language/Version**: Python 3.12 (Home Assistant requirement)

**Primary Dependencies**: Home Assistant core (config_entries, services, entity registry), `voluptuous`, `homeassistant.components.switch`

**Storage**: `config_entry.data` — same location as all other control entity references

**Testing**: pytest + pytest-asyncio; existing `AsyncMock`/`MagicMock` harness in `tests/test_export_block_control.py`

**Target Platform**: Home Assistant custom component (HACS-compatible)

**Project Type**: HA integration / custom component

**Performance Goals**: N/A — triggered at most once per minute by scheduler

**Constraints**: Must not block event loop; must call HA services via `hass.services.async_call`; must respect test-mode guard in `controllers/inverter.py`

**Scale/Scope**: Single new config key, logic change in one decision-engine file, additions to config flow and translations, new tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Rule | Status | Notes |
|------|--------|-------|
| Config via config_flow only | ✅ PASS | New field added to control_entities step in both ConfigFlow and OptionsFlow |
| No hard-coded English entity names | ✅ PASS | New field uses translation labels in en.json |
| Sterowanie przez serwisy HA | ✅ PASS | Uses `turn_on_switch` / `turn_off_switch` from `controllers/inverter.py` |
| Degradacja kontrolowana | ✅ PASS | When off-grid switch not configured → falls back to existing surplus-switch path |
| No VERSION bump for backward-compatible optional key | ✅ PASS | `.get()` returns None for old entries; no migration needed |
| No new HA entity platform | ✅ PASS | No new sensor/switch entity; external switch referenced by entity_id |
| Testy dla nowej ścieżki decyzyjnej | ✅ PASS | 7 new test cases added |
| No external PyPI dependency | ✅ PASS | Uses only existing HA abstractions |

**No constitution violations.**

## Project Structure

### Documentation (this feature)

```text
specs/005-inverter-offgrid-zero-price/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── quickstart.md        ← Phase 1 output
└── checklists/
    └── requirements.md
```

### Source Code (files to be changed)

```text
custom_components/energy_optimizer/
├── const.py                                  # + CONF_INVERTER_OFFGRID_SWITCH
├── config_flow.py                            # + field in ConfigFlow + OptionsFlow control_entities; + validation
├── decision_engine/
│   └── export_block_control.py               # + off-grid branch (priority over surplus-switch)
└── translations/
    └── en.json                               # + labels for inverter_offgrid_switch field

tests/
└── test_export_block_control.py              # + 7 new test cases
```

**Structure Decision**: Single-project layout. No new files — all changes are additions to existing files.

---

## Implementation Tasks

### Task 1 — `const.py`: Add new constant

**File**: `custom_components/energy_optimizer/const.py`

After line:
```python
CONF_INVERTER_EXPORT_SURPLUS_SWITCH = "inverter_export_surplus_switch"
```

Add:
```python
CONF_INVERTER_OFFGRID_SWITCH = "inverter_offgrid_switch"
```

---

### Task 2 — `config_flow.py` (ConfigFlow): Add field to `async_step_control_entities`

**File**: `custom_components/energy_optimizer/config_flow.py`

**2a) Import**: Add `CONF_INVERTER_OFFGRID_SWITCH` to the import block alongside `CONF_INVERTER_EXPORT_SURPLUS_SWITCH`.

**2b) Schema** in `EnergyOptimizerConfigFlow.async_step_control_entities`: Add after `CONF_INVERTER_EXPORT_SURPLUS_SWITCH` entry:

```python
vol.Optional(CONF_INVERTER_OFFGRID_SWITCH): selector.EntitySelector(
    selector.EntitySelectorConfig(domain="switch")
),
```

**2c) Validation** in `_validate_control_entities`: Add after the existing surplus-switch validation block:

```python
offgrid_switch = user_input.get(CONF_INVERTER_OFFGRID_SWITCH)
if offgrid_switch:
    self._validate_entity(
        entity_id=offgrid_switch,
        field=CONF_INVERTER_OFFGRID_SWITCH,
        errors=errors,
        expected_domain="switch",
        domain_error="not_switch_entity",
    )
```

---

### Task 3 — `config_flow.py` (OptionsFlow): Add field to `async_step_control_entities`

**File**: `custom_components/energy_optimizer/config_flow.py`

In `EnergyOptimizerOptionsFlow.async_step_control_entities`, add after `CONF_INVERTER_EXPORT_SURPLUS_SWITCH` entry:

```python
vol.Optional(
    CONF_INVERTER_OFFGRID_SWITCH,
    default=self._config_entry.data.get(CONF_INVERTER_OFFGRID_SWITCH),
): selector.EntitySelector(
    selector.EntitySelectorConfig(domain="switch")
),
```

---

### Task 4 — `export_block_control.py`: Add off-grid branch

**File**: `custom_components/energy_optimizer/decision_engine/export_block_control.py`

**4a) Import**: Add `CONF_INVERTER_OFFGRID_SWITCH` to the imports from `..const`.

**4b) Logic**: After the price read and before the existing surplus-switch state read, insert the off-grid branch:

```python
offgrid_switch = config.get(CONF_INVERTER_OFFGRID_SWITCH)
if offgrid_switch:
    offgrid_state = hass.states.get(str(offgrid_switch))
    if offgrid_state is None:
        _LOGGER.warning(
            "Export block control: off-grid switch entity %s unavailable — skip",
            offgrid_switch,
        )
        return

    is_offgrid = str(offgrid_state.state).lower() == "on"
    desired_offgrid = round(price, 1) <= 0

    _LOGGER.info(
        "Export block control (off-grid path): price=%.4f, switch=%s, desired=%s",
        price,
        "on" if is_offgrid else "off",
        "on" if desired_offgrid else "off",
    )

    if desired_offgrid == is_offgrid:
        _LOGGER.debug(
            "Export block control: no change — off-grid switch already in desired state (%s)",
            "on" if is_offgrid else "off",
        )
        return

    if desired_offgrid:
        _LOGGER.info(
            "Export block control: activating off-grid mode (price %.4f, switch off -> on)",
            price,
        )
        await turn_on_switch(
            hass,
            str(offgrid_switch),
            entry=entry,
            logger=_LOGGER,
            context=Context(),
        )
    else:
        _LOGGER.info(
            "Export block control: deactivating off-grid mode (price %.4f, switch on -> off)",
            price,
        )
        await turn_off_switch(
            hass,
            str(offgrid_switch),
            entry=entry,
            logger=_LOGGER,
            context=Context(),
        )
    return  # do not proceed to surplus-switch path
```

The existing surplus-switch code that follows is left **unchanged**.

---

### Task 5 — `translations/en.json`: Add labels

**File**: `custom_components/energy_optimizer/translations/en.json`

In the `control_entities` step's `data` section, add after `inverter_export_surplus_switch`:

```json
"inverter_offgrid_switch": "Inverter OffGrid Switch (Optional)"
```

In the `control_entities` step's `data_description` section, add:

```json
"inverter_offgrid_switch": "Switch used to disconnect the inverter from the grid (on = off-grid, off = grid-connected). When configured, this switch is activated instead of the export surplus switch when sell price is zero or negative."
```

---

### Task 6 — `tests/test_export_block_control.py`: New test cases

**File**: `tests/test_export_block_control.py`

**6a) Import**: Add `CONF_INVERTER_OFFGRID_SWITCH` to existing const import.

**6b) Constants**: Add `_OFFGRID_SWITCH = "switch.inverter_offgrid"`.

**6c) Helper**: Add `_setup_hass_with_offgrid()` based on `_setup_hass()` that sets `CONF_INVERTER_OFFGRID_SWITCH` in entry data and adds the off-grid switch entity to the mock states.

**6d) Test cases**:

| Test | Setup | Expected |
|------|-------|----------|
| `test_offgrid_turns_on_when_price_zero_and_switch_off` | price=0.0, offgrid=off | `turn_on` called on offgrid switch |
| `test_offgrid_turns_off_when_price_positive_and_switch_on` | price=50, offgrid=on | `turn_off` called on offgrid switch |
| `test_offgrid_no_action_when_price_zero_and_already_on` | price=0.0, offgrid=on | no service call |
| `test_offgrid_no_action_when_price_positive_and_already_off` | price=50, offgrid=off | no service call |
| `test_offgrid_surplus_switch_not_touched_when_offgrid_configured` | price=0.0, offgrid=off, surplus=on | only offgrid toggled, surplus NOT called |
| `test_offgrid_no_action_when_sun_not_above_horizon` | sun=below_horizon, price=0.0 | no service call |
| `test_offgrid_entity_unavailable_skip` | offgrid entity missing | no service call |

---

## Complexity Tracking

No constitution violations. No complexity justification required.

---

## Risk & Rollback

| Risk | Mitigation |
|------|-----------|
| Off-grid switch stays ON after price recovery | Price > 0 path turns switch OFF; covered by test 2 |
| Breaking existing surplus-switch tests | Off-grid branch added before surplus path; surplus path untouched |
| Config entry corruption | No schema change; `.get()` safe on old entries |
| Off-grid activated at night | Sun guard runs before all switch logic; covered by test 6 |