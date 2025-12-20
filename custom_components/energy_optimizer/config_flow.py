"""Config flow for Energy Optimizer integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AVERAGE_PRICE_SENSOR,
    CONF_BATTERY_CAPACITY_AH,
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_CURRENT_SENSOR,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_VOLTAGE,
    CONF_BATTERY_VOLTAGE_SENSOR,
    CONF_CHARGE_CURRENT_ENTITY,
    CONF_CHEAPEST_WINDOW_SENSOR,
    CONF_COP_CURVE,
    CONF_DAILY_LOAD_SENSOR,
    CONF_DISCHARGE_CURRENT_ENTITY,
    CONF_ENABLE_HEAT_PUMP,
    CONF_EXPENSIVE_WINDOW_SENSOR,
    CONF_GRID_CHARGE_SWITCH,
    CONF_HEAT_PUMP_POWER_SENSOR,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_PV_FORECAST_REMAINING,
    CONF_PV_FORECAST_TODAY,
    CONF_PV_FORECAST_TOMORROW,
    CONF_PV_PEAK_FORECAST,
    CONF_TARGET_SOC_ENTITY,
    CONF_TOMORROW_PRICE_SENSOR,
    CONF_WEATHER_FORECAST,
    CONF_WORK_MODE_ENTITY,
    DEFAULT_BATTERY_CAPACITY_AH,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_BATTERY_VOLTAGE,
    DEFAULT_COP_CURVE,
    DEFAULT_MAX_SOC,
    DEFAULT_MIN_SOC,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class EnergyOptimizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Energy Optimizer."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            return await self.async_step_price_entities()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={
                "docs": "Energy Optimizer coordinates battery charging based on prices and PV forecasts.\n\n"
                "**Recommended Integrations** (install from HACS):\n"
                "- ha-rce-pse: Electricity pricing and windows\n"
                "- ha-solarman: Battery and inverter control\n"
                "- Solcast Solar: PV forecasting (optional)"
            },
        )

    async def async_step_price_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle price entity configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate entities
            errors = await self._validate_price_entities(user_input)
            if not errors:
                self._data.update(user_input)
                return await self.async_step_battery_sensors()

        schema = vol.Schema(
            {
                vol.Required(CONF_PRICE_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_AVERAGE_PRICE_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_CHEAPEST_WINDOW_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor")
                ),
                vol.Optional(CONF_EXPENSIVE_WINDOW_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor")
                ),
                vol.Optional(CONF_TOMORROW_PRICE_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
            }
        )

        return self.async_show_form(
            step_id="price_entities", data_schema=schema, errors=errors
        )

    async def async_step_battery_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle battery sensor configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_battery_sensors(user_input)
            if not errors:
                self._data.update(user_input)
                return await self.async_step_battery_params()

        schema = vol.Schema(
            {
                vol.Required(CONF_BATTERY_SOC_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="battery",
                    )
                ),
                vol.Required(CONF_BATTERY_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="power",
                    )
                ),
                vol.Optional(CONF_BATTERY_VOLTAGE_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="voltage",
                    )
                ),
                vol.Optional(CONF_BATTERY_CURRENT_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="current",
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="battery_sensors", data_schema=schema, errors=errors
        )

    async def async_step_battery_params(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle battery parameter configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = self._validate_battery_params(user_input)
            if not errors:
                self._data.update(user_input)
                return await self.async_step_control_entities()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BATTERY_CAPACITY_AH, default=DEFAULT_BATTERY_CAPACITY_AH
                ): vol.All(vol.Coerce(float), vol.Range(min=1, max=1000)),
                vol.Required(
                    CONF_BATTERY_VOLTAGE, default=DEFAULT_BATTERY_VOLTAGE
                ): vol.All(vol.Coerce(float), vol.Range(min=12, max=400)),
                vol.Required(
                    CONF_BATTERY_EFFICIENCY, default=DEFAULT_BATTERY_EFFICIENCY
                ): vol.All(vol.Coerce(float), vol.Range(min=50, max=100)),
                vol.Required(CONF_MIN_SOC, default=DEFAULT_MIN_SOC): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=100)
                ),
                vol.Required(CONF_MAX_SOC, default=DEFAULT_MAX_SOC): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=100)
                ),
                vol.Optional(CONF_BATTERY_CAPACITY_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
            }
        )

        return self.async_show_form(
            step_id="battery_params", data_schema=schema, errors=errors
        )

    async def async_step_control_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle control entity configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_control_entities(user_input)
            if not errors:
                self._data.update(user_input)
                return await self.async_step_pv_load_config()

        schema = vol.Schema(
            {
                vol.Required(CONF_TARGET_SOC_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(CONF_WORK_MODE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="select")
                ),
                vol.Optional(CONF_CHARGE_CURRENT_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(CONF_DISCHARGE_CURRENT_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(CONF_GRID_CHARGE_SWITCH): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
            }
        )

        return self.async_show_form(
            step_id="control_entities", data_schema=schema, errors=errors
        )

    async def async_step_pv_load_config(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle PV forecast and load sensor configuration."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_heat_pump()

        schema = vol.Schema(
            {
                vol.Optional(CONF_DAILY_LOAD_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_PV_FORECAST_TODAY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_PV_FORECAST_TOMORROW): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_PV_FORECAST_REMAINING): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_PV_PEAK_FORECAST): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_WEATHER_FORECAST): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="weather")
                ),
            }
        )

        return self.async_show_form(step_id="pv_load_config", data_schema=schema)

    async def async_step_heat_pump(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle heat pump configuration."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_review()

        schema = vol.Schema(
            {
                vol.Optional(CONF_ENABLE_HEAT_PUMP, default=False): selector.BooleanSelector(),
                vol.Optional(CONF_OUTSIDE_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="temperature",
                    )
                ),
                vol.Optional(CONF_HEAT_PUMP_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="power",
                    )
                ),
            }
        )

        return self.async_show_form(step_id="heat_pump", data_schema=schema)

    async def async_step_review(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Review and create entry."""
        if user_input is not None:
            # Create config entry
            return self.async_create_entry(
                title="Energy Optimizer",
                data=self._data,
            )

        # Display configured entities for review
        review_data = {
            "Price Sensor": self._data.get(CONF_PRICE_SENSOR, "Not configured"),
            "Battery SOC": self._data.get(CONF_BATTERY_SOC_SENSOR, "Not configured"),
            "Target SOC Control": self._data.get(
                CONF_TARGET_SOC_ENTITY, "Not configured"
            ),
            "Battery Capacity": f"{self._data.get(CONF_BATTERY_CAPACITY_AH, 0)} Ah",
            "Battery Voltage": f"{self._data.get(CONF_BATTERY_VOLTAGE, 0)} V",
        }

        description = "Review your configuration:\n\n" + "\n".join(
            [f"- **{k}**: {v}" for k, v in review_data.items()]
        )

        return self.async_show_form(
            step_id="review",
            data_schema=vol.Schema({}),
            description_placeholders={"review": description},
        )

    async def _validate_price_entities(
        self, user_input: dict[str, Any]
    ) -> dict[str, str]:
        """Validate price entity configuration."""
        errors = {}

        # Check price sensor
        price_state = self.hass.states.get(user_input[CONF_PRICE_SENSOR])
        if not price_state:
            errors[CONF_PRICE_SENSOR] = "entity_not_found"
        elif not self._is_numeric_state(price_state.state):
            errors[CONF_PRICE_SENSOR] = "not_numeric"

        # Check average price sensor
        avg_state = self.hass.states.get(user_input[CONF_AVERAGE_PRICE_SENSOR])
        if not avg_state:
            errors[CONF_AVERAGE_PRICE_SENSOR] = "entity_not_found"
        elif not self._is_numeric_state(avg_state.state):
            errors[CONF_AVERAGE_PRICE_SENSOR] = "not_numeric"

        return errors

    async def _validate_battery_sensors(
        self, user_input: dict[str, Any]
    ) -> dict[str, str]:
        """Validate battery sensor configuration."""
        errors = {}

        # Check SOC sensor
        soc_state = self.hass.states.get(user_input[CONF_BATTERY_SOC_SENSOR])
        if not soc_state:
            errors[CONF_BATTERY_SOC_SENSOR] = "entity_not_found"
        elif not self._is_numeric_state(soc_state.state):
            errors[CONF_BATTERY_SOC_SENSOR] = "not_numeric"

        # Check power sensor
        power_state = self.hass.states.get(user_input[CONF_BATTERY_POWER_SENSOR])
        if not power_state:
            errors[CONF_BATTERY_POWER_SENSOR] = "entity_not_found"
        elif not self._is_numeric_state(power_state.state):
            errors[CONF_BATTERY_POWER_SENSOR] = "not_numeric"

        return errors

    def _validate_battery_params(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Validate battery parameter configuration."""
        errors = {}

        # Check min/max SOC relationship
        if user_input[CONF_MIN_SOC] >= user_input[CONF_MAX_SOC]:
            errors[CONF_MIN_SOC] = "min_greater_than_max"

        return errors

    async def _validate_control_entities(
        self, user_input: dict[str, Any]
    ) -> dict[str, str]:
        """Validate control entity configuration."""
        errors = {}

        # Check target SOC entity exists and is writable
        target_state = self.hass.states.get(user_input[CONF_TARGET_SOC_ENTITY])
        if not target_state:
            errors[CONF_TARGET_SOC_ENTITY] = "entity_not_found"
        elif target_state.domain != "number":
            errors[CONF_TARGET_SOC_ENTITY] = "not_number_entity"

        return errors

    def _is_numeric_state(self, state: str) -> bool:
        """Check if state is numeric."""
        try:
            float(state)
            return True
        except (ValueError, TypeError):
            return False

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return EnergyOptimizerOptionsFlow(config_entry)


class EnergyOptimizerOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Energy Optimizer."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Update config entry
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, **user_input}
            )
            return self.async_create_entry(title="", data={})

        # Allow reconfiguring key parameters
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MIN_SOC,
                    default=self.config_entry.data.get(CONF_MIN_SOC, DEFAULT_MIN_SOC),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Optional(
                    CONF_MAX_SOC,
                    default=self.config_entry.data.get(CONF_MAX_SOC, DEFAULT_MAX_SOC),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Optional(
                    CONF_BATTERY_EFFICIENCY,
                    default=self.config_entry.data.get(
                        CONF_BATTERY_EFFICIENCY, DEFAULT_BATTERY_EFFICIENCY
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=50, max=100)),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
