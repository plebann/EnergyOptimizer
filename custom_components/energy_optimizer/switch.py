"""Switch platform for Energy Optimizer integration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    AUTOMATION_AFTERNOON_CHARGE,
    AUTOMATION_EVENING_BEHAVIOR,
    AUTOMATION_EVENING_SELL,
    AUTOMATION_EXPORT_BLOCK_CONTROL,
    AUTOMATION_MORNING_CHARGE,
    AUTOMATION_MORNING_SELL,
    AUTOMATION_SOLAR_CHARGE_BLOCK,
    CONF_TEST_MODE,
    CONF_USE_PV_FORECAST_COMPENSATION,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.core import HomeAssistant


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Energy Optimizer switches from a config entry."""
    test_mode_switch = TestModeSwitch(config_entry)
    pv_forecast_compensation_switch = PvForecastCompensationSwitch(config_entry)
    automation_switches = {
        description.key: AutomationSwitch(config_entry, description)
        for description in _AUTOMATION_SWITCHES
    }
    async_add_entities(
        [
            test_mode_switch,
            pv_forecast_compensation_switch,
            *automation_switches.values(),
        ]
    )

    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(config_entry.entry_id, {})
    entry_data["test_mode_switch"] = test_mode_switch
    entry_data["pv_forecast_compensation_switch"] = pv_forecast_compensation_switch
    entry_data["automation_switches"] = automation_switches


class TestModeSwitch(SwitchEntity, RestoreEntity):
    """Switch controlling test mode for Energy Optimizer."""

    _attr_has_entity_name = True
    _attr_translation_key = "test_mode"
    _attr_icon = "mdi:test-tube"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the test mode switch."""
        self._attr_is_on = False
        self._attr_unique_id = f"{config_entry.entry_id}_test_mode_switch"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": "Energy Optimizer",
            "manufacturer": "Energy Optimizer",
            "model": "Battery Optimizer",
        }
        self._entry_data = config_entry.data

    async def async_added_to_hass(self) -> None:
        """Restore last state when added to hass."""
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"
            return

        if CONF_TEST_MODE in self._entry_data:
            self._attr_is_on = bool(self._entry_data.get(CONF_TEST_MODE))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn test mode on."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn test mode off."""
        self._attr_is_on = False
        self.async_write_ha_state()


@dataclass(frozen=True, slots=True)
class _AutomationSwitchDescription:
    """Description of an independently controlled scheduler automation."""

    key: str
    translation_key: str
    icon: str


_AUTOMATION_SWITCHES = (
    _AutomationSwitchDescription(AUTOMATION_MORNING_CHARGE, "morning_charge_automation", "mdi:battery-clock"),
    _AutomationSwitchDescription(AUTOMATION_AFTERNOON_CHARGE, "afternoon_charge_automation", "mdi:battery-clock-outline"),
    _AutomationSwitchDescription(AUTOMATION_MORNING_SELL, "morning_sell_automation", "mdi:transmission-tower-export"),
    _AutomationSwitchDescription(AUTOMATION_EVENING_SELL, "evening_sell_automation", "mdi:transmission-tower-export"),
    _AutomationSwitchDescription(AUTOMATION_SOLAR_CHARGE_BLOCK, "solar_charge_block_automation", "mdi:weather-sunny-alert"),
    _AutomationSwitchDescription(AUTOMATION_EXPORT_BLOCK_CONTROL, "export_block_control_automation", "mdi:transmission-tower-off"),
    _AutomationSwitchDescription(AUTOMATION_EVENING_BEHAVIOR, "night_management_automation", "mdi:weather-night"),
)


class AutomationSwitch(SwitchEntity, RestoreEntity):
    """Persistent switch that enables one scheduler-only automation."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: _AutomationSwitchDescription,
    ) -> None:
        """Initialize an enabled-by-default automation switch."""
        self._description = description
        self._attr_is_on = True
        self._attr_translation_key = description.translation_key
        self._attr_icon = description.icon
        self._attr_unique_id = f"{config_entry.entry_id}_{description.key}_automation_switch"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": "Energy Optimizer",
            "manufacturer": "Energy Optimizer",
            "model": "Battery Optimizer",
        }
        self._entry_id = config_entry.entry_id

    async def async_added_to_hass(self) -> None:
        """Restore the last selected state, defaulting to enabled."""
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    def _refresh_schedule(self) -> None:
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        if isinstance(entry_data, dict):
            callback = entry_data.get("charge_completion_snapshot_callback")
            if callback is not None:
                callback()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the automation from its next scheduler trigger."""
        self._attr_is_on = True
        self.async_write_ha_state()
        self._refresh_schedule()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the automation from its next scheduler trigger."""
        self._attr_is_on = False
        self.async_write_ha_state()
        self._refresh_schedule()


class PvForecastCompensationSwitch(SwitchEntity, RestoreEntity):
    """Switch controlling PV compensation sensor usage in forecast calculations."""

    _attr_has_entity_name = True
    _attr_translation_key = "pv_forecast_compensation_usage"
    _attr_icon = "mdi:chart-line-variant"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the PV forecast compensation usage switch."""
        self._attr_is_on = True
        self._attr_unique_id = (
            f"{config_entry.entry_id}_pv_forecast_compensation_switch"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": "Energy Optimizer",
            "manufacturer": "Energy Optimizer",
            "model": "Battery Optimizer",
        }
        self._entry_data = config_entry.data

    async def async_added_to_hass(self) -> None:
        """Restore last state when added to hass."""
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"
            return

        if CONF_USE_PV_FORECAST_COMPENSATION in self._entry_data:
            self._attr_is_on = bool(
                self._entry_data.get(CONF_USE_PV_FORECAST_COMPENSATION)
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable PV forecast compensation usage."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable PV forecast compensation usage."""
        self._attr_is_on = False
        self.async_write_ha_state()