# GitHub Copilot Instructions for Home Assistant Custom Integration

## Project Context

This project is a Home Assistant custom integration that must be compatible with HACS (Home Assistant Community Store). All code must follow Home Assistant development standards and HACS validation requirements.

## Core Requirements

### Integration Structure
- Domain: `heat_pump_predictor`
- All integration files must be in `custom_components/heat_pump_predictor/`
- Follow the structure documented in `.copilot-tracking/research/20241221-hacs-compatible-integration-research.md`

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

### Setup Entry
```python
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    coordinator = MyCoordinator(hass, entry.data)
    await coordinator.async_config_entry_first_refresh()
    
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True
```

### Unload Entry
```python
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
```

### Device Info
```python
from homeassistant.helpers.device_registry import DeviceInfo

device_info = DeviceInfo(
    identifiers={(DOMAIN, unique_id)},
    name="Device Name",
    manufacturer="Manufacturer",
    model="Model",
    sw_version="1.0.0",
)
```

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

1. **Check research document** first: `.copilot-tracking/research/20241221-hacs-compatible-integration-research.md`
2. **Follow Home Assistant patterns** exactly as documented
3. **Include proper typing** with type hints
4. **Add docstrings** to all public functions/classes
5. **Handle errors** gracefully with try/except
6. **Log appropriately** using the module logger
7. **Write tests** alongside implementation code

## Useful Commands

```bash
# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=custom_components.heat_pump_predictor --cov-report=term-missing

# Lint code
pre-commit run --all-files

# Format code
ruff format .

# Check types
mypy custom_components/heat_pump_predictor
```

## Reference Documentation

- Research: `.copilot-tracking/research/20241221-hacs-compatible-integration-research.md`
- HA Docs: https://developers.home-assistant.io/
- HACS Docs: https://hacs.xyz/docs/publish/integration
- Entity: https://developers.home-assistant.io/docs/core/entity
- Config Entries: https://developers.home-assistant.io/docs/config_entries_index
