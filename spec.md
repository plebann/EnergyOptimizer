# Energy Optimizer — Integration Specification

**Version:** 1.0-draft  
**Status:** Living document — normative for all new development  
**Audience:** Contributors, AI coding agents, and maintainers

---

## Table of Contents

1. [Vision & Scope](#1-vision--scope)
2. [Project Purpose](#2-project-purpose)
3. [Tech Stack](#3-tech-stack)
4. [Architectural Principles](#4-architectural-principles)
5. [Naming Conventions](#5-naming-conventions)
6. [Constraints](#6-constraints)

---

## 1. Vision & Scope

### 1.1 Vision

Energy Optimizer will be a price-aware, PV-integrated battery management system delivered as a Home Assistant custom integration (HACS-compatible). The system will minimise electricity bills over a rolling 12-month horizon by automating battery charge and discharge decisions based on real-time and forecast data, without requiring manual intervention from the user.

The integration will operate conservatively: avoiding purchases of expensive-tariff energy will always take precedence over speculative arbitrage opportunities.

### 1.2 Scope

**In scope:**

- Automated decision-making at defined daily action points (overnight, morning, afternoon, evening peaks).
- Price-aware charge scheduling using the user's selected tariff logic.
- PV forecast integration (Solcast) to compute surplus and adjust SOC targets.
- Spot-price arbitrage using buy/sell prices provided by external integrations, within defined safety margins.
- Battery balancing (full charge) on a configurable cadence.
- Optional domestic hot water (DHW) heat-pump coordination.
- Diagnostic sensors exposing decision rationale and history.
- Full UI-based setup and configuration via Home Assistant Config Flow.
- HACS distribution and compliance.

**Out of scope (for v1):**

- Grid-export peak shaving beyond what is achievable through existing inverter program slots.

---

## 2. Project Purpose

### 2.1 Primary Goal

Energy Optimizer will minimise the annual electricity bill for a prosumer household with a PV installation and battery storage by:

1. Maximising PV self-consumption so that generated energy is used locally rather than exported at a lower net-billing rate.
2. Eliminating grid consumption during high-tariff periods whenever stored or forecasted PV energy is sufficient.
3. Building a prosumer deposit during high-PV months to offset costs in low-PV months.
4. Executing spot-price arbitrage — selling at price peaks and buying in the off-peak window — up to the net daily PV yield ceiling.

### 2.2 Strategy

The system will follow a **conservative strategy**: safe energy coverage MUST be guaranteed before any speculative arbitrage action is taken. The integration MUST NOT cause the battery to drop below the configured minimum SOC during high-tariff hours in pursuit of arbitrage profit.

### 2.3 Target Installation Profile

The integration is designed for, but not limited to, the following reference installation:

| Parameter | Reference Value |
| --- | --- |
| PV capacity | 13 kWp |
| Battery capacity | 21 kWh |
| Inverter | Deye SUN-5-25K-SG01HP3 (12 kW) |
| Round-trip efficiency | 90 % |
| Electricity tariff | G12 (dual-zone) |
| Settlement model | Net-billing with prosumer deposit |

Configuration MUST be parameterised so that other installations can substitute their own values through the UI without code changes.

---

## 3. Tech Stack

### 3.1 Runtime Environment

| Component | Requirement |
| --- | --- |
| Platform | Home Assistant Core (latest stable) |
| Language | Python 3.12+ |
| Distribution | HACS custom integration |
| Integration domain | `energy_optimizer` |

### 3.2 Home Assistant APIs

The integration MUST use only stable, public Home Assistant APIs:

- `homeassistant.config_entries` — Config Flow and Options Flow for UI setup.
- `homeassistant.helpers.update_coordinator` — `DataUpdateCoordinator` for all polling.
- `homeassistant.helpers.event` — `async_track_time_interval`, `async_track_state_change_event` for scheduled and reactive triggers.
- `homeassistant.helpers.entity_platform` — platform registration for `sensor`, `binary_sensor`, and `switch`.
- `homeassistant.helpers.storage` — persistent lightweight state (e.g., sell-restore flags).
- Home Assistant `notify` services — user-facing decision notifications delivered via the `notify` service mechanism.

The integration MUST NOT rely on internal/private HA APIs (modules prefixed with `_` or documented as internal).

### 3.3 External Integrations

The integration SHOULD work with the following companion HACS integrations when they are installed:

| HA Domain | HACS Repository | Data Provided |
| --- | --- | --- |
| `solarman` | davidrapan/ha-solarman | Inverter and battery control entities |
| `solcast_solar` | BJReplay/ha-solcast-solar | PV production forecasts |
| `rce_pse` | Lewa-Reka/ha-rce-pse | Spot electricity prices (15-min resolution) — current provider, subject to change |
| `heat_pump_predictor` | plebann/HeatPumpPredictor | Heat pump energy forecast |

All four domains MUST be listed in `manifest.json` under `after_dependencies` so that Energy Optimizer loads after them. The integration MUST degrade gracefully when an optional integration is absent: missing optional sensor entities MUST disable only the dependent feature branch, not the entire integration.

### 3.4 Testing

- All business logic MUST be covered by unit tests in the `tests/` directory.
- Tests MUST use `pytest` with `pytest-asyncio` for async test cases.
- Tests MUST NOT import integration modules directly from outside `tests/`; they MUST go through `hass.config_entries` or helper factories.
- **Current state:** the existing test suite imports `custom_components.energy_optimizer.*` modules directly in many places (decision engine, config flow, calculations). A future refactor is planned to align the test suite with this requirement. Until that refactor is complete, direct module imports are tolerated but MUST NOT be extended to new test files.
- The test suite MUST remain green before any PR is merged.

---

## 4. Architectural Principles

### 4.1 Layered Architecture

The integration MUST follow a strict layered architecture:

```
┌─────────────────────────────────────────────┐
│  Home Assistant Platform Layer              │
│  (sensor.py, binary_sensor.py, switch.py)   │
├─────────────────────────────────────────────┤
│  Entity Layer                               │
│  (entities/base.py, entities/sensors/)      │
├─────────────────────────────────────────────┤
│  Coordinator Layer                          │
│  (coordinator.py)                           │
├─────────────────────────────────────────────┤
│  Decision Engine Layer                      │
│  (decision_engine/*.py)                     │
├─────────────────────────────────────────────┤
│  Calculation Layer                          │
│  (calculations/*.py)                        │
├─────────────────────────────────────────────┤
│  Controller / Service Layer                 │
│  (controllers/*.py, service_handlers/*.py)  │
└─────────────────────────────────────────────┘
```

Upper layers MAY call downward; lower layers MUST NOT call upward into platform or entity code.

### 4.2 Async-First

All I/O operations, Home Assistant API calls, and any function that can block MUST be implemented as `async def` coroutines. Synchronous blocking calls (e.g., `time.sleep`, blocking HTTP requests) MUST NOT appear in integration code. Compute-heavy pure functions that are not I/O-bound MAY be synchronous.

### 4.3 Decision Engine Design

- Each daily action point (overnight, morning charge, morning sell, afternoon charge, evening sell, evening behaviour) MUST have its own module in `decision_engine/`.
- Each decision engine module MUST expose a public `async_run_*()` entry-point function at module level. This entry point MUST be the sole surface called by service handlers and scheduler triggers.
- Business safety guards (minimum SOC enforcement, arbitrage ceiling checks, balancing-in-progress flags) MUST live inside decision engine functions so that the same protections apply whether the function is called from a scheduler trigger or a direct service call.
- Decision outcomes MUST be returned as a `DecisionOutcome` dataclass (or equivalent), separating:
  - `key_metrics` — concise, human-readable summary for history views and notifications.
  - `full_details` — numeric diagnostics for sensor attributes and deep inspection.
- **Current state:** the existing `DecisionOutcome` dataclass (in `utils/logging.py`) uses `summary`, `reason`, and `details` fields, which do not match the `key_metrics`/`full_details` shape above. This mismatch will be resolved in a future refactoring pass that aligns the dataclass with this spec.

### 4.4 Coordinator Pattern

- Sensor data refresh MUST be managed through coordinator-based polling using `DataUpdateCoordinator`.
- The current implementation uses a single `DataUpdateCoordinator` with one shared refresh cadence.
- Unless and until the implementation is changed, the coordinator refresh interval MUST reflect the current 5-minute `update_interval` rather than a separate fast/slow split.
- A future split between fast-refresh and slow-refresh data MAY be introduced later, but it MUST NOT be treated as normative until the implementation actually supports it.
- Entities MUST extend `CoordinatorEntity` and MUST NOT poll Home Assistant states independently.
- Coordinators MUST raise `UpdateFailed` on transient errors rather than swallowing exceptions silently.

### 4.5 Scheduler Design

- Time-based triggers (overnight at 22:00, morning at 04:00, etc.) MUST be registered through the `ActionScheduler` in `scheduler/action_scheduler.py`.
- State-change–based listeners (e.g., reacting to sun position or inverter mode changes) SHOULD be registered inline in the relevant `start()` method using `async_track_state_change_event`, without a dedicated `_schedule_*` wrapper, unless the listener itself involves time recalculation.
- The scheduler MUST support clean teardown: all listeners and time callbacks MUST be unregistered when the config entry is unloaded.

### 4.6 Config Flow

- All configuration MUST be done through Home Assistant Config Flow (UI-based). YAML-only configuration MUST NOT be introduced.
- The config flow MUST implement `async_step_user()` for initial setup.
- Options that can be adjusted post-setup MUST be available via an Options Flow (`async_step_init()`).
- All user-facing form schemas MUST use `voluptuous` for validation.
- Errors MUST be surfaced to the user via `errors` dict return values, not via unhandled exceptions.

### 4.7 Entity Design

- All entities MUST set `_attr_has_entity_name = True`.
- The primary feature entity for a device MUST set `_attr_name = None` so it inherits the device name.
- Secondary entities MUST use a `translation_key` backed by an entry in `translations/en.json`; any additional language files that exist (e.g. `translations/pl.json`) MUST be kept in parity with `en.json`.
- Hard-coded English strings MUST NOT appear as entity names.
- Every entity MUST have a stable `unique_id` composed of the config entry ID and a deterministic suffix.
- Entities MUST register against the device registry via `DeviceInfo`.

### 4.8 Persistence

- Lightweight cross-restart state (e.g., sell-restore flags, last-balancing timestamp) MUST use `homeassistant.helpers.storage`.
- Entities that must restore their `native_value` after HA restart MUST extend `RestoreSensor` / `RestoreEntity` and implement `async_added_to_hass()` to reload state.
- Heavy diagnostic history (snapshots, scheduled action lists) MUST be stored in entity `extra_state_attributes`, not in `native_value`.

### 4.9 Error Handling

- The integration MUST NOT swallow exceptions silently. Every `except` block MUST at minimum log the error at `WARNING` or `ERROR` level.
- Optional sensor reads MUST use a helper pattern (e.g., `get_float_state_info()`) that returns a sentinel/`None` rather than raising, so that the absence of an optional sensor only disables the dependent feature branch.
- Mandatory sensor reads MUST use a helper (e.g., `get_required_float_state()`) that raises a descriptive `HomeAssistantError` or returns a safe fallback with a logged warning.

---

## 5. Naming Conventions

### 5.1 Python Modules

| Artifact | Convention | Example |
| --- | --- | --- |
| Module files | `snake_case.py` | `morning_charge.py` |
| Classes | `PascalCase` | `MorningChargeEngine` |
| Functions / methods | `snake_case` | `async_run_morning_charge()` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_MIN_SOC` |
| Private helpers | leading underscore | `_compute_deficit()` |

### 5.2 Config Entry Keys

- Config entry data keys MUST be prefixed with `CONF_` and defined as constants in `const.py`.
- Keys MUST use `snake_case` string values matching the Python constant suffix, e.g. `CONF_BATTERY_SOC_SENSOR = "battery_soc_sensor"`.

### 5.3 Services

- Service names MUST be `snake_case` and registered in `services.yaml`.
- Service constants MUST be prefixed with `SERVICE_` in `const.py`.
- Public entry-point functions that implement services MUST be named `async_run_<service_name>()`.

### 5.4 Entities & Translation Keys

- `translation_key` values MUST be `snake_case` and MUST have matching entries in every translation file.
- `unique_id` format MUST be `{config_entry_id}_{descriptor}` where `descriptor` is a stable `snake_case` string.
- Entity platform module names MUST match HA platform names: `sensor.py`, `binary_sensor.py`, `switch.py`.

### 5.5 Tests

- Test files MUST be named `test_<subject>.py` and placed in the `tests/` directory.
- Test functions MUST be named `test_<scenario>()` using `snake_case`.
- Fixtures MUST be defined in `conftest.py` at the appropriate scope level.

---

## 6. Constraints

### 6.1 Safety Constraints

- The integration MUST enforce a configurable minimum SOC floor at all times. Battery SOC MUST NOT be commanded below `min_soc` during high-tariff periods.
- During a balancing cycle, all other charge/discharge actions MUST be suppressed until the cycle completes.
- Arbitrage sell actions MUST be capped so that total sold energy does not exceed the net PV yield for the day.
- The integration MUST expose a test mode (`CONF_TEST_MODE`) that logs all decisions and commands without writing to inverter entities.

### 6.2 Performance Constraints

- The coordinator fast-refresh cycle MUST complete within 10 seconds under normal HA load.
- Decision engine functions MUST NOT perform network I/O; all data MUST be read from HA state or coordinator cache.
- The integration MUST NOT start more than two `DataUpdateCoordinator` instances per config entry.

### 6.3 Compatibility Constraints

- The integration MUST remain compatible with the current stable Home Assistant release and MUST NOT use APIs marked as deprecated.
- The integration MUST pass HACS validation checks (`hacs/action` GitHub Action) before any release.
- `manifest.json` MUST specify a `version` in SemVer format and MUST be updated for every release.
- All required manifest fields (`domain`, `name`, `version`, `codeowners`, `documentation`, `issue_tracker`, `config_flow`, `integration_type`, `iot_class`) MUST be present and valid.

### 6.4 Quality Constraints

- Every PR MUST maintain or increase unit-test coverage for modified modules.
- Every new decision engine module MUST include at least one happy-path and one error-path test.
- No hard-coded credentials, API keys, or personally identifiable information MAY appear in source code or committed files.
- All user-facing strings MUST be externalised to `translations/en.json`; Polish translations in `translations/pl.json` MUST be kept in sync if that file exists.

### 6.5 Coding Style Constraints

- Code MUST be formatted with `ruff format` and MUST pass `ruff check` with the project configuration.
- Type hints MUST be present on all public function signatures.
- Imports MUST follow the order: `from __future__ import annotations`, standard library, third-party (HA), local, with blank lines between groups.
- Docstrings MUST be present on all public classes and public functions.

---

*End of specification*
