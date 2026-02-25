# GitHub Copilot Instructions for Home Assistant Custom Integration

## Project Context

This project is a Home Assistant custom integration that must be compatible with HACS (Home Assistant Community Store). All code must follow Home Assistant development standards and HACS validation requirements.

## Core Requirements

### Integration Structure
- Domain: `energy_optimizer`
- All integration files must be in `custom_components/energy_optimizer/`
- Follow the structure documented in `.copilot-tracking/research/20241221-hacs-compatible-integration-research.md` and audit notes in `.copilot-tracking/research/20260212-copilot-instructions-audit-research.md`

### Mandatory Patterns

**Entity Naming (CRITICAL):**
- ALL entities MUST have `_attr_has_entity_name = True`
- Main feature entities: `_attr_name = None` (inherits device name)
- Additional entities: use `translation_key` or descriptive `_attr_name`
- Never hard-code English names; use translations

**Config Flow:**
- All setup MUST use config flow (UI-based, no YAML)
- Implement `async_step_user()` for initial setup
- Use `voluptuous` for input validation
- Handle errors gracefully with proper error messages

**Async Patterns:**
- Use `async def` for all I/O operations
- Use `await` for coordinator updates
- Never block the event loop with synchronous I/O

### Code Standards

**Import Order:**
```python
from __future__ import annotations

# Standard library
import logging
from typing import Any

# Third-party libraries
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

# Local imports
from .const import DOMAIN
from .coordinator import MyCoordinator
```

**Entity Implementation:**
```python
class MySensorEntity(CoordinatorEntity, SensorEntity):
    """Sensor entity."""
    
    _attr_has_entity_name = True
    
    def __init__(self, coordinator: MyCoordinator, description: SensorEntityDescription):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.unique_id}_{description.key}"
        self._attr_device_info = coordinator.device_info
```

**Coordinator Pattern:**
- Use `DataUpdateCoordinator` for polling
- Set appropriate `update_interval` (minimum 30 seconds for cloud APIs)
- Raise `UpdateFailed` on errors, don't swallow exceptions
- Entities should extend `CoordinatorEntity`

### Testing Requirements

- Test via `async_setup_component()` or `hass.config_entries.async_setup()`
- Assert entity states via `hass.states.get(entity_id)`
- Use `MockConfigEntry` for config entry tests
- Never import integration modules directly in tests
- Use snapshot testing for complex outputs

### manifest.json Rules

Required fields:
- `domain`: must match directory name
- `name`: human-readable name
- `version`: SemVer format (e.g., "1.0.0")
- `codeowners`: GitHub usernames with @
- `documentation`: full GitHub URL
- `issue_tracker`: full GitHub issues URL
- `config_flow`: true (for new integrations)
- `integration_type`: hub/device/service/etc.
- `iot_class`: cloud_polling/local_push/etc.

### HACS Validation

Ensure:
- README.md exists with clear documentation
- Repository has description and topics
- No hard-coded credentials or API keys
- Proper error handling for network failures
- Entities have unique_id for customization
- Device registry integration when applicable

## Common Patterns

- Setup entry: store coordinator in `hass.data`, call `async_config_entry_first_refresh`, forward platforms.
- Unload entry: unload platforms and remove entry from `hass.data`.
- Device info: register device via `DeviceInfo` on entities.
- See `.copilot-tracking/research/20241221-hacs-compatible-integration-research.md` for full examples.

## Avoid These Mistakes

- ❌ Don't use YAML configuration (use config flow)
- ❌ Don't hard-code entity names in English
- ❌ Don't forget `_attr_has_entity_name = True`
- ❌ Don't block the event loop with sync I/O
- ❌ Don't import integration code directly in tests
- ❌ Don't swallow exceptions without logging
- ❌ Don't forget to implement `async_unload_entry`
- ❌ Don't use `setup_platform()` (deprecated)

## When Generating Code

1. **Check research documents** first: `.copilot-tracking/research/20260212-copilot-instructions-audit-research.md` and `.copilot-tracking/research/20241221-hacs-compatible-integration-research.md`
2. **Follow Home Assistant patterns** exactly as documented
3. **Include proper typing** with type hints
4. **Add docstrings** to all public functions/classes
5. **Handle errors** gracefully with try/except
6. **Log appropriately** using the module logger
7. **Write tests** alongside implementation code

## Useful Commands

```bash
# Preferred: run tests from Ubuntu WSL for this workspace
# (use explicit distro/user to avoid shell translation issues)
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/ -q'

# First-time WSL setup for tests (create local venv + install pytest)
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; python3 -m venv .venv-wsl; ./.venv-wsl/bin/python -m pip install pytest'

# Run tests (full suite) in WSL
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/ -v'

# Run a single test file in WSL (adjust path)
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/test_helpers.py -v'

# Run matching tests by keyword in WSL
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/ -k "test_name" -v'

# Run with coverage in WSL
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/ --cov=custom_components.energy_optimizer --cov-report=term-missing'

# Update snapshots (syrupy, if configured in repo) in WSL
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/ --snapshot-update'

# Fast smoke set used during decision engine refactors
wsl -d Ubuntu-24.04 -u mpleb -- bash -lc 'cd /mnt/c/Users/mpleb/Sources/EnergyOptimizer; ./.venv-wsl/bin/python -m pytest tests/test_decision_engine_morning.py tests/test_decision_engine_evening_sell.py tests/test_decision_engine_evening.py -q'

# Note: Tests may emit DEBUG/WARNING/INFO logs from the integration; this is normal if tests still pass.
# Note: Full test run can take several seconds; allow it to complete before interrupting.
# Note: If `wsl -e bash -lc ...` fails on this machine, use explicit `-d Ubuntu-24.04 -u mpleb` as above.

# Lint code (if configured in repo)
pre-commit run --all-files

# Format code (if configured in repo)
ruff format .

# Check types (if configured in repo)
mypy custom_components/energy_optimizer
```

## Reference Documentation

- Research: `.copilot-tracking/research/20260212-copilot-instructions-audit-research.md`
- Research: `.copilot-tracking/research/20241221-hacs-compatible-integration-research.md`
- HA Docs: https://developers.home-assistant.io/
- HACS Docs: https://hacs.xyz/docs/publish/integration
- Entity: https://developers.home-assistant.io/docs/core/entity
- Config Entries: https://developers.home-assistant.io/docs/config_entries_index
