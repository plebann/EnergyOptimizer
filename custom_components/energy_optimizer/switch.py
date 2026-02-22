"""Switch platform for Energy Optimizer integration."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_TEST_MODE, CONF_TEST_SELL_MODE, DOMAIN

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
    test_sell_mode_switch = TestSellModeSwitch(config_entry)
    async_add_entities([test_mode_switch, test_sell_mode_switch])

    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(config_entry.entry_id, {})
    entry_data["test_mode_switch"] = test_mode_switch
    entry_data["test_sell_mode_switch"] = test_sell_mode_switch


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


class TestSellModeSwitch(SwitchEntity, RestoreEntity):
    """Switch controlling test sell mode for evening sell actions."""

    _attr_has_entity_name = True
    _attr_translation_key = "test_sell_mode"
    _attr_icon = "mdi:transmission-tower-export"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the test sell mode switch."""
        self._attr_is_on = False
        self._attr_unique_id = f"{config_entry.entry_id}_test_sell_mode_switch"
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

        if CONF_TEST_SELL_MODE in self._entry_data:
            self._attr_is_on = bool(self._entry_data.get(CONF_TEST_SELL_MODE))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn test sell mode on."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn test sell mode off."""
        self._attr_is_on = False
        self.async_write_ha_state()