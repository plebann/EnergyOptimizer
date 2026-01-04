# Home Assistant Integration Development Conventions

## File Organization

### Required Files
```
custom_components/heat_pump_predictor/
├── __init__.py              # Integration setup/teardown
├── manifest.json            # Integration metadata
├── config_flow.py           # UI configuration
├── const.py                 # Constants and defaults
├── coordinator.py           # Data update coordinator
├── sensor.py                # Sensor platform
├── binary_sensor.py         # Binary sensor platform
├── strings.json             # Base translations
└── translations/            # Language-specific translations
    └── en.json
```

### Optional Files
```
├── switch.py                # Switch platform
├── number.py                # Number platform
├── select.py                # Select platform
├── button.py                # Button platform
├── diagnostics.py           # Diagnostic data
├── services.yaml            # Service definitions
└── icons.json               # Entity icon mappings
```

## Naming Conventions

### Files
- Lowercase with underscores: `heat_pump_predictor.py`
- Platform files match HA domains: `sensor.py`, `switch.py`
- Test files prefixed: `test_init.py`, `test_config_flow.py`

### Classes
- PascalCase: `HeatPumpCoordinator`, `HeatPumpSensor`
- Suffix with type: `*Entity`, `*Coordinator`, `*ConfigFlow`

### Functions
- snake_case: `async_setup_entry`, `async_get_data`
- Async functions prefixed: `async_*`

### Constants
- UPPERCASE: `DOMAIN`, `DEFAULT_SCAN_INTERVAL`, `CONF_API_KEY`
- Group in const.py

### Entity IDs
- Format: `{domain}.{device}_{feature}`
- Example: `sensor.heat_pump_temperature`
- Automatically generated from unique_id

## Type Hints

Always include type hints:

```python
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up from config entry."""
    ...
```

## Error Handling

### Network Errors
```python
from homeassistant.exceptions import ConfigEntryNotReady

try:
    await client.connect()
except ConnectionError as err:
    raise ConfigEntryNotReady(f"Unable to connect: {err}") from err
```

### Update Errors
```python
from homeassistant.helpers.update_coordinator import UpdateFailed

try:
    return await self.client.get_data()
except ApiError as err:
    raise UpdateFailed(f"Error fetching data: {err}") from err
```

### Config Flow Errors
```python
errors = {}
try:
    await validate_input(user_input)
except ValueError:
    errors["base"] = "invalid_auth"
except Exception:  # pylint: disable=broad-except
    errors["base"] = "unknown"
```

## Logging

```python
import logging

_LOGGER = logging.getLogger(__name__)

# Use appropriate log levels
_LOGGER.debug("Detailed information: %s", data)
_LOGGER.info("Setup complete for %s", entry.entry_id)
_LOGGER.warning("Deprecated feature used: %s", feature)
_LOGGER.error("Failed to update data: %s", error)
```

## Device Registry Integration

When integration manages physical devices:

```python
from homeassistant.helpers.device_registry import DeviceInfo

class MyEntity(CoordinatorEntity, SensorEntity):
    """Entity with device info."""
    
    def __init__(self, coordinator, device_id):
        """Initialize."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=f"Heat Pump {device_id}",
            manufacturer="ACME Corp",
            model="HP-2000",
            sw_version="1.2.3",
            configuration_url="http://device.local/config",
        )
        self._attr_unique_id = f"{device_id}_temperature"
```

## Translation Keys

### strings.json
```json
{
  "config": {
    "step": {
      "user": {
        "title": "Set up Heat Pump Predictor",
        "data": {
          "host": "Host",
          "api_key": "API Key"
        }
      }
    },
    "error": {
      "cannot_connect": "Failed to connect",
      "invalid_auth": "Invalid authentication",
      "unknown": "Unexpected error occurred"
    }
  },
  "entity": {
    "sensor": {
      "temperature": {
        "name": "Temperature"
      },
      "power_consumption": {
        "name": "Power consumption"
      }
    }
  }
}
```

## Entity Descriptions

Use dataclasses for entity descriptions:

```python
from dataclasses import dataclass
from homeassistant.components.sensor import (
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature

@dataclass(frozen=True)
class HeatPumpSensorDescription(SensorEntityDescription):
    """Describes a heat pump sensor."""
    
    value_fn: Callable[[dict], Any] | None = None

SENSOR_TYPES: tuple[HeatPumpSensorDescription, ...] = (
    HeatPumpSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("temp"),
    ),
)
```

## Config Entry Data Storage

```python
# Coordinator/client stored in hass.data
hass.data.setdefault(DOMAIN, {})
hass.data[DOMAIN][entry.entry_id] = coordinator

# Access in platform setup
coordinator = hass.data[DOMAIN][entry.entry_id]

# Clean up on unload
if unload_ok:
    hass.data[DOMAIN].pop(entry.entry_id)
```

## Platform Setup Pattern

```python
from homeassistant.helpers.entity_platform import AddEntitiesCallback

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator: HeatPumpCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = [
        HeatPumpSensor(coordinator, description)
        for description in SENSOR_TYPES
    ]
    
    async_add_entities(entities)
```

## Update Methods

### Polling (via Coordinator)
```python
class MyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for polling updates."""
    
    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API."""
        return await self.client.get_data()

class MyEntity(CoordinatorEntity):
    """Entity that polls via coordinator."""
    
    @property
    def native_value(self):
        """Return the state."""
        return self.coordinator.data.get("value")
```

### Push Updates
```python
class MyEntity(SensorEntity):
    """Entity that receives push updates."""
    
    _attr_should_poll = False
    
    async def async_added_to_hass(self) -> None:
        """Subscribe to updates."""
        self.async_on_remove(
            self.device.subscribe(self._handle_update)
        )
    
    def _handle_update(self, data: dict) -> None:
        """Handle pushed data."""
        self._attr_native_value = data["value"]
        self.async_write_ha_state()
```

## Services

If adding custom services, define in services.yaml:

```yaml
set_mode:
  name: Set operating mode
  description: Set the heat pump operating mode
  fields:
    mode:
      name: Mode
      description: The operating mode to set
      required: true
      selector:
        select:
          options:
            - heat
            - cool
            - auto
```

Register in __init__.py:

```python
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from config entry."""
    # ... setup code ...
    
    async def handle_set_mode(call):
        """Handle set_mode service."""
        mode = call.data.get("mode")
        await coordinator.set_mode(mode)
    
    hass.services.async_register(
        DOMAIN,
        "set_mode",
        handle_set_mode,
    )
    
    return True
```

## Version Compatibility

Support Home Assistant's supported Python versions:
- Currently: Python 3.12+
- Check HA's requirements.txt for current version

Pin dependency versions in manifest.json:
```json
{
  "requirements": ["aioclient==1.2.3"]
}
```
