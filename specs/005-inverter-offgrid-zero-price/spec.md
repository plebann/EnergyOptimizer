# Feature Specification: Inverter Off-Grid Mode on Zero Sell Price

**Feature Branch**: `005-inverter-offgrid-zero-price`

**Created**: 2026-06-20

**Status**: Draft

**Input**: User description: "zmiana funkcjonalności — kiedy ceny sprzedaży prądu są uznawane za zerowe, zamiast włączać ograniczenie eksportu do sieci (surplus) należy przestawić falownik w tryb off-grid; nowy switch (input w integracji, konfigurowany w config/options) trzymający stan Inverter OffGrid (off = podpięty do sieci, on = odpięty); jeżeli ceny są zerowe → Inverter OffGrid na on"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Automatic Off-Grid on Zero Price (Priority: P1)

When the current sell price is effectively zero (rounds to 0.0 at 1 decimal place; price < 0.05 PLN/kWh, matching the existing export-block comparison pattern), the system automatically switches the inverter to off-grid mode by turning on the configured Inverter OffGrid switch, rather than activating the export-surplus limitation as it did before.

**Why this priority**: Prevents feeding electricity into the grid at zero or negative prices, which can cause financial loss. Off-grid mode is a stronger, cleaner response than capping export power.

**Independent Test**: Configure the Inverter OffGrid switch entity. Set the sell price sensor to 0.00. Trigger export block control. Verify the Inverter OffGrid switch turns ON and the export surplus switch is NOT toggled.

**Acceptance Scenarios**:

1. **Given** the sell price is 0.00 (≤ threshold), **When** export block control runs, **Then** the Inverter OffGrid switch is turned ON (off-grid mode activated).
2. **Given** the sell price is 0.00 and the Inverter OffGrid switch is already ON, **When** export block control runs, **Then** no service call is made (idempotent).
3. **Given** the sell price is 0.04 (below threshold), **When** export block control runs, **Then** the Inverter OffGrid switch is turned ON.

---

### User Story 2 - Automatic Grid Reconnect on Positive Price (Priority: P1)

When the sell price is no longer effectively zero (≥ 0.05 PLN/kWh; rounds above zero at 1 decimal place), the system automatically turns off the Inverter OffGrid switch (returns inverter to grid-connected mode).

**Why this priority**: Without automatic reversal, the inverter stays off-grid permanently even when prices recover, preventing solar export and normal operation.

**Independent Test**: Set Inverter OffGrid switch to ON. Raise sell price to 0.20. Trigger export block control. Verify Inverter OffGrid switch turns OFF.

**Acceptance Scenarios**:

1. **Given** the Inverter OffGrid switch is ON and price rises to > threshold, **When** export block control runs, **Then** the Inverter OffGrid switch is turned OFF (grid mode restored).
2. **Given** the Inverter OffGrid switch is already OFF and price is > threshold, **When** export block control runs, **Then** no service call is made.

---

### User Story 3 - Configuration via Options Flow (Priority: P2)

A user can configure the Inverter OffGrid switch entity from the integration's Options (and initial Config) flow, without editing YAML or restarting Home Assistant.

**Why this priority**: Without configuration, the feature cannot be activated. It must follow the existing HA config-flow pattern used by other switches in the integration.

**Independent Test**: Open integration Options in HA UI. Provide a switch entity ID for Inverter OffGrid. Save options. Verify the entity ID is stored and the export block control logic reads it correctly on next trigger.

**Acceptance Scenarios**:

1. **Given** the integration is already set up, **When** the user opens Options and sets the Inverter OffGrid switch entity, **Then** the value is saved and used on the next export-block evaluation.
2. **Given** the Inverter OffGrid switch is not configured, **When** export block control runs, **Then** the system falls back to the previous export-surplus-switch behavior (or skips if neither is configured).

---

### User Story 4 - No Off-Grid at Night (Priority: P2)

When the sun is below the horizon, the Inverter OffGrid switch is not activated regardless of price, matching the existing daytime-only guard for export block control.

**Why this priority**: Switching off-grid at night is pointless and could disrupt household grid consumption unnecessarily.

**Independent Test**: Set sun to below_horizon. Set price to 0.00. Trigger export block control. Verify Inverter OffGrid switch is NOT changed.

**Acceptance Scenarios**:

1. **Given** sun is below the horizon, **When** sell price is zero and export block control runs, **Then** no switch is changed.

---

### Edge Cases

- What happens when the Inverter OffGrid switch entity is configured but unavailable in HA? → Log a warning and skip, same as the current surplus-switch guard.
- What if both Inverter OffGrid switch AND export-surplus switch are configured? → When prices are zero, only the Inverter OffGrid switch is activated; the export-surplus switch is not touched.
- What if only the export-surplus switch is configured (no Inverter OffGrid)? → Retain the existing behavior for backward compatibility.
- What if the sell price sensor returns an unavailable/unknown state? → Skip execution (existing behavior).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST turn ON the Inverter OffGrid switch when sell price is effectively zero (rounds to 0.0 at 1 decimal place; price < 0.05 PLN/kWh) and the sun is above the horizon.
- **FR-002**: System MUST turn OFF the Inverter OffGrid switch when sell price rises above the zero-price threshold and the Inverter OffGrid switch is currently ON.
- **FR-003**: System MUST NOT activate the export-surplus switch when the Inverter OffGrid switch is configured and the price is zero; the two behaviors are mutually exclusive.
- **FR-004**: System MUST retain the existing export-surplus switch behavior when no Inverter OffGrid switch is configured (backward compatibility).
- **FR-005**: Users MUST be able to configure the Inverter OffGrid switch entity via the integration's Config and Options flow (UI-based, no YAML).
- **FR-006**: System MUST skip Inverter OffGrid control when the sun is below the horizon.
- **FR-007**: System MUST skip Inverter OffGrid control when the configured switch entity is unavailable, logging a warning.
- **FR-008**: System MUST be idempotent: if the switch is already in the desired state, no service call is made.

### Key Entities

- **Inverter OffGrid Switch** (`CONF_INVERTER_OFFGRID_SWITCH`): An optional Home Assistant switch entity ID provided by the user. When ON, the inverter is disconnected from the grid (off-grid mode). When OFF, the inverter is connected to the grid (normal mode).
- **Sell Price Sensor**: Existing entity providing the current sell price in PLN/kWh. Used unchanged.
- **Export Surplus Switch** (`CONF_INVERTER_EXPORT_SURPLUS_SWITCH`): Existing optional switch. Only used when the Inverter OffGrid switch is NOT configured (backward-compatible path).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: When sell price drops to zero, the inverter is switched to off-grid mode within the next scheduled export-block-control evaluation (typically within 1 minute).
- **SC-002**: When sell price recovers above threshold, the inverter returns to grid-connected mode within the next scheduled evaluation.
- **SC-003**: Configuring the Inverter OffGrid switch requires no HA restart; changes take effect at the next evaluation cycle.
- **SC-004**: No regression: all existing export-surplus-switch tests continue to pass without modification when no Inverter OffGrid switch is configured.
- **SC-005**: All new scenarios (zero-price → off-grid, positive-price → grid reconnect, night guard, fallback) are covered by automated tests.

## Assumptions

- The zero-price constant `ZERO_PRICE_THRESHOLD = 0.05` from `calculations/price_windows.py` is reused unchanged; no new threshold is introduced. The effective price comparison is `round(price, 1) <= 0` — the same pattern as the existing export-surplus switch — which corresponds to prices < 0.05 PLN/kWh.
- The new switch entity reference is stored in `entry.data` (like other switch references) and mirrored in options flow for user-editable updates.
- The Inverter OffGrid switch is optional. The integration continues to function without it.
- The sun-above-horizon guard is preserved from the current export block control logic.
- The Inverter OffGrid switch is a physical or virtual HA switch entity controlled externally (e.g., by a Modbus/inverter integration); this feature only sets its on/off state.
- Polish-language entity names and translations will follow the existing translation-key pattern used by other switches.
