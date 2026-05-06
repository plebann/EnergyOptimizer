# Feature Specification: Energy Optimizer Core Integration

**Feature Branch**: `[001-core-integration]`  
**Created**: 2026-05-05  
**Status**: Draft  
**Input**: User description: "Energy Optimizer core integration"

## Clarifications

### Session 2026-05-05

- Q: Jaki zakres ma obejmować "core integration"? → A: Setup + wszystkie aktualnie publiczne workflow usługowe + diagnostyka.
- Q: Jaki ma być docelowy czas wykonania core workflows dla typowej konfiguracji? → A: 5 sekund.
- Q: Czy core integration wspiera jeden config entry czy wiele? → A: Core integration wspiera tylko jeden config entry w instancji Home Assistant.

### Session 2026-05-06

- Q: Czy minimalna konfiguracja musi zawierać komplet encji sterujących potrzebnych do realnej aktuacji workflow? → A: Tak, minimalna konfiguracja musi zawierać komplet encji sterujących potrzebnych do realnej aktuacji workflow.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Configure the Integration (Priority: P1)

A Home Assistant user configures the Energy Optimizer integration through the UI by selecting the required battery, price, and control entities so that the optimizer can start operating on real household energy data.

Minimalna konfiguracja objęta tą specyfikacją obejmuje nie tylko dane wejściowe, ale także komplet encji sterujących wymaganych do rzeczywistego wykonania workflow usługowych znajdujących się w zakresie core integration.

**Why this priority**: Without a successful setup flow, none of the optimization or monitoring capabilities are usable.

**Independent Test**: The user can add the integration from the Home Assistant UI, provide the required entity mappings and core parameters, and complete setup without editing YAML or using external tooling.

**Acceptance Scenarios**:

1. **Given** the user has compatible Home Assistant entities for prices, battery state, and control targets, **When** they complete the setup flow with required values, **Then** the integration is created successfully and becomes available for use.
2. **Given** the user omits a required input or selects invalid data, **When** they try to continue setup, **Then** the integration blocks completion and shows a clear validation error.

---

### User Story 2 - Run Core Optimization Workflows (Priority: P2)

A Home Assistant user runs the core optimization workflows so that the integration can calculate and trigger planned charging, selling, or overnight battery behavior using the configured inputs.

W zakresie tej specyfikacji mieszczą się wszystkie aktualnie publiczne workflow usługowe integracji: `overnight_schedule`, `morning_grid_charge`, `afternoon_grid_charge`, `evening_peak_sell`, `morning_peak_sell` oraz `solar_charge_block`.

**Why this priority**: The main value of the integration is the ability to make and apply energy optimization decisions.

**Independent Test**: After setup, the user can trigger at least one supported optimization workflow and observe that the integration evaluates current inputs and produces a resulting action or no-action decision.

**Acceptance Scenarios**:

1. **Given** the integration is configured and the required source entities have valid states, **When** the user triggers an optimization workflow, **Then** the integration evaluates the available data and executes the corresponding decision path.
2. **Given** an optional data source is missing, **When** the user triggers a workflow that can still operate safely, **Then** the integration completes the workflow with reduced scope instead of failing the whole run.
3. **Given** an Energy Optimizer configuration already exists, **When** the user tries to add another core integration entry, **Then** the setup flow rejects the attempt with a clear single-instance error.

---

### User Story 3 - Observe Decisions and State (Priority: P3)

A Home Assistant user inspects the integration's sensors, binary sensors, and switches so that they can understand recent optimization decisions, current control modes, and the daily action schedule.

**Why this priority**: Operational trust depends on being able to inspect what the integration decided and why.

**Independent Test**: After setup and at least one workflow run, the user can inspect exposed entities and confirm that the integration publishes diagnostic state useful for monitoring and troubleshooting.

**Acceptance Scenarios**:

1. **Given** the integration has run at least one optimization workflow, **When** the user inspects the related entities, **Then** they can see the latest decision result, relevant diagnostic context, and current control state.
2. **Given** Home Assistant restarts, **When** the integration loads again, **Then** persisted diagnostic and control-oriented entities restore their last meaningful state where continuity is required.

### Edge Cases

- What happens when required source entities are available during setup but later become unavailable or non-numeric at runtime?
- How does the integration behave when minimal required control entities are present, but optional forecast or advanced control inputs are absent?
- What happens when a user tries to configure the core integration a second time in the same Home Assistant instance?
- How does the integration behave after a Home Assistant restart if the last diagnostic state or control flag was previously set?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST allow a user to create the Energy Optimizer integration through a Home Assistant UI-based setup flow.
- **FR-002**: The system MUST validate required setup inputs before creating the integration entry.
- **FR-003**: The system MUST store the entity mappings and operating parameters needed to evaluate optimization decisions for the configured household.
- **FR-004**: The system MUST require the minimum set of control entities needed to execute the in-scope workflow services during setup of the core integration.
- **FR-005**: The system MUST expose the core Energy Optimizer entities needed for monitoring, diagnostics, and runtime control after setup completes.
- **FR-006**: The system MUST register the core Energy Optimizer services that allow users or automations to trigger supported optimization workflows.
- **FR-007**: The system MUST evaluate optimization workflows using the current states of configured Home Assistant entities.
- **FR-008**: The system MUST support scheduled and manually triggered execution of the core optimization workflows.
- **FR-009**: The system MUST publish the outcome of optimization runs in a way that lets users inspect recent decisions and current schedule state.
- **FR-010**: The system MUST degrade safely when optional inputs are unavailable, while still preventing execution when required inputs are missing or invalid.
- **FR-011**: The system MUST restore persisted diagnostic or control state after restart when continuity is required for user understanding or runtime safety.
- **FR-012**: The system MUST enforce a single-instance setup model for the core integration within one Home Assistant instance.
- **FR-013**: The system MUST reject creation of a second core integration entry with a clear user-facing error.
- **FR-014**: The system MUST be installable and maintainable as a Home Assistant custom integration distributed through the expected repository structure for HACS-compatible integrations.
- **FR-015**: The system MUST include all currently public workflow services of the integration in the scope of the core feature: `overnight_schedule`, `morning_grid_charge`, `afternoon_grid_charge`, `evening_peak_sell`, `morning_peak_sell`, and `solar_charge_block`.

### Non-functional Requirements

- **NFR-001**: Core workflows SHOULD complete evaluation and publish outcomes within 5 seconds for a typical configuration.
- **NFR-002**: User-facing error messages during setup MUST be understandable by non-technical users (no raw exception strings).
- **NFR-003**: The feature MUST not introduce blocking I/O or long-running sync calls in the HA event loop.

### Key Entities *(include if feature involves data)*

- **Integration Configuration**: The persistent setup record that binds one Energy Optimizer instance to a specific set of Home Assistant source and control entities.
- **Optimization Workflow**: A user-triggered or scheduled decision path that evaluates current household energy conditions and decides whether to charge, sell, block, restore, or leave the system unchanged.
- **Diagnostic State**: The published state and attributes that describe the latest decision, schedule snapshot, balancing state, or control mode.
- **Control Target**: A configured Home Assistant entity that the integration can influence indirectly through Home Assistant services when a workflow decides to act.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can complete initial setup of the integration using only the Home Assistant UI in under 10 minutes when the required entities already exist.
- **SC-002**: 100% of setup attempts with missing required inputs are rejected before the integration entry is created.
- **SC-003**: A configured user can trigger each core optimization workflow and receive either an actionable result or a clear safe no-action outcome without an unhandled failure.
- **SC-004**: After at least one workflow run, users can inspect a published diagnostic state that identifies the latest decision context for the active integration entry.
- **SC-005**: After Home Assistant restart, persisted diagnostic or control-oriented entities recover their previous meaningful state for at least 95% of normal restart scenarios.
- **SC-006**: 100% of attempts to create a second core integration entry are rejected before duplicate runtime state is created.
- **SC-007**: 100% of setup attempts that omit required control entities for in-scope workflow execution are rejected before the integration entry is created.

## Assumptions

- Users already have compatible Home Assistant entities for price, battery, and control data before starting setup.
- The core integration scope covers the primary optimizer setup, workflow triggering, and observability surfaces rather than every optional future scenario.
- The core integration is intentionally specified as single-instance even if broader multi-entry support may exist or be considered outside this feature.
- The minimum supported configuration includes the control entities required to execute the in-scope workflow services, not only read-only inputs.
- Home Assistant services and entity states remain the integration boundary; direct device communication is out of scope for this feature.
- Optional forecast and advanced control inputs improve decision quality but are not required for the minimum viable configuration.
