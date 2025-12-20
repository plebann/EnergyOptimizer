---
applyTo: '.copilot-tracking/changes/20241219-energy-optimizer-implementation-changes.md'
---
<!-- markdownlint-disable-file -->
# Task Checklist: Energy Optimizer HACS Integration Implementation

## Overview

Migrate Energy Optimizer from YAML-based automations to a HACS-distributable Home Assistant custom integration with entity-based configuration, calculation library, sensor platform, and automation services.

## Objectives

- Create HACS-compliant custom integration structure with proper manifest and metadata
- Implement 9-step config flow for entity selection and battery configuration
- Build calculation library (battery physics, energy balance, charging optimization, heat pump estimation)
- Create sensor platform with calculated energy metrics
- Implement services for on-demand optimization calculations
- Maintain compatibility with external integrations (ha-rce-pse, ha-solarman, Solcast)

## Research Summary

### Project Files
- `automations.yaml` - 12 numbered automations implementing energy optimization logic
- `custom_templates/*.jinja` - Calculation macros for battery, energy, charging, heat pump
- `python_scripts/*.py` - Price window finding algorithms (now handled by ha-rce-pse)
- `sensors.yaml` / `templates.yaml` - Template sensors for calculations

### External References
- #file:../research/20241219-energy-optimizer-hacs-migration-research.md - Main implementation guide with key tasks
- #file:../research/20241219-config-flow-specification.md - Complete 9-step config flow with EntitySelector patterns
- #file:../research/20241219-architecture-summary.md - Architecture, data flow, service specifications
- #file:../research/20241219-ha-rce-pse-integration-guide.md - Price sensor entities for config flow
- #file:../research/20241219-ha-solarman-integration-guide.md - Battery/inverter entities for config flow
- #file:../research/20241219-solcast-pv-forecast-integration-guide.md - PV forecast entities (optional)

### Standards References
- #file:../../copilot/python.md - Python conventions for Home Assistant integrations
- HACS integration requirements (manifest, structure, quality scale)
- Home Assistant config flow patterns and EntitySelector usage

## Implementation Checklist

### [ ] Phase 1: Project Structure & Manifest

- [ ] Task 1.1: Create integration directory structure
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 15-35)

- [ ] Task 1.2: Create manifest.json with metadata and dependencies
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 37-80)

- [ ] Task 1.3: Create const.py with domain constants and configuration keys
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 82-120)

- [ ] Task 1.4: Create __init__.py with integration entry points
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 122-165)

### [ ] Phase 2: Configuration Flow Implementation

- [ ] Task 2.1: Implement config_flow.py base structure with FlowHandler
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 167-210)

- [ ] Task 2.2: Implement Step 1-2 (Introduction & Price Entity Selection)
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 212-265)

- [ ] Task 2.3: Implement Step 3-4 (Battery Sensors & Parameters)
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 267-320)

- [ ] Task 2.4: Implement Step 5-6 (Control Entities & Load/Forecast Config)
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 322-375)

- [ ] Task 2.5: Implement Step 7-9 (Heat Pump, Review, Options Flow)
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 377-430)

- [ ] Task 2.6: Create strings.json with config flow translations
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 432-475)

### [ ] Phase 3: Calculation Library

- [ ] Task 3.1: Create calculations/__init__.py and base utilities
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 477-515)

- [ ] Task 3.2: Implement calculations/battery.py (SOC conversion, reserve, space)
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 517-575)

- [ ] Task 3.3: Implement calculations/charging.py (multi-phase current, charge time)
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 577-630)

- [ ] Task 3.4: Implement calculations/energy.py (required energy, balance, surplus)
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 632-690)

- [ ] Task 3.5: Implement calculations/heat_pump.py (temperature-based COP, consumption)
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 692-745)

### [ ] Phase 4: Sensor Platform

- [ ] Task 4.1: Create sensor.py with platform setup and coordinator integration
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 747-795)

- [ ] Task 4.2: Implement battery sensors (reserve, space, capacity)
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 797-850)

- [ ] Task 4.3: Implement energy balance sensors (required energy, surplus/deficit)
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 852-905)

- [ ] Task 4.4: Implement heat pump estimation sensor
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 907-950)

### [ ] Phase 5: Service Implementation

- [ ] Task 5.1: Create services.yaml with service definitions
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 952-1010)

- [ ] Task 5.2: Implement calculate_charge_soc service
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 1012-1070)

- [ ] Task 5.3: Implement calculate_sell_energy service
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 1072-1125)

- [ ] Task 5.4: Implement estimate_heat_pump_usage service
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 1127-1175)

- [ ] Task 5.5: Implement optimize_battery_schedule service
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 1177-1235)

### [ ] Phase 6: Testing & Validation

- [ ] Task 6.1: Create unit tests for calculation library
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 1237-1285)

- [ ] Task 6.2: Create integration tests with mocked entities
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 1287-1335)

- [ ] Task 6.3: Validate config flow with various entity configurations
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 1337-1375)

### [ ] Phase 7: Documentation & HACS Compliance

- [ ] Task 7.1: Create README.md with installation and setup instructions
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 1377-1425)

- [ ] Task 7.2: Create HACS compliance files (hacs.json, info.md)
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 1427-1465)

- [ ] Task 7.3: Create migration guide from YAML configuration
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 1467-1515)

- [ ] Task 7.4: Create automation blueprint templates
  - Details: .copilot-tracking/details/20241219-energy-optimizer-implementation-details.md (Lines 1517-1565)

## Dependencies

- **Home Assistant Core**: 2024.1.0 or later (for EntitySelector and config flow features)
- **Python**: 3.11+ (Home Assistant requirement)
- **Recommended External Integrations** (user installs separately):
  - ha-rce-pse: Price data and window sensors
  - ha-solarman: Battery/inverter control entities
  - Solcast Solar: PV forecast (optional)
- **No PyPI Requirements**: Uses Python standard library only

## Success Criteria

- Integration installs via HACS without errors
- Config flow completes successfully with entity selection and validation
- All sensors calculate correct values matching Jinja template logic
- Services execute and return accurate calculation results
- Integration handles missing external integrations gracefully
- Unit tests achieve >90% code coverage for calculation library
- Documentation enables migration from YAML configuration
- HACS validation passes for default repository listing
- Performance impact < 1% CPU, < 50MB memory
