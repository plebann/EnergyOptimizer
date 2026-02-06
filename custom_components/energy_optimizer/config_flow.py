"""Config flow for Energy Optimizer integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
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
    CONF_BALANCING_PV_THRESHOLD,
    CONF_BALANCING_INTERVAL_DAYS,
    CONF_CHARGE_CURRENT_ENTITY,
    CONF_CHEAPEST_WINDOW_SENSOR,
    CONF_DAILY_LOAD_SENSOR,
    CONF_DAILY_LOSSES_SENSOR,
    CONF_DISCHARGE_CURRENT_ENTITY,
    CONF_ENABLE_HEAT_PUMP,
    CONF_EXPENSIVE_WINDOW_SENSOR,
    CONF_GRID_CHARGE_SWITCH,
    CONF_HEAT_PUMP_FORECAST_DOMAIN,
    CONF_HEAT_PUMP_FORECAST_SERVICE,
    CONF_HEAT_PUMP_POWER_SENSOR,
    CONF_LOAD_USAGE_00_04,
    CONF_LOAD_USAGE_04_08,
    CONF_LOAD_USAGE_08_12,
    CONF_LOAD_USAGE_12_16,
    CONF_LOAD_USAGE_16_20,
    CONF_LOAD_USAGE_20_24,
    CONF_MAX_CHARGE_CURRENT_ENTITY,
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_PRICE_SENSOR,
    CONF_PROG1_SOC_ENTITY,
    CONF_PROG1_TIME_START_ENTITY,
    CONF_PROG2_SOC_ENTITY,
    CONF_PROG2_TIME_START_ENTITY,
    CONF_PROG3_SOC_ENTITY,
    CONF_PROG3_TIME_START_ENTITY,
    CONF_PROG4_SOC_ENTITY,
    CONF_PROG4_TIME_START_ENTITY,
    CONF_PROG5_SOC_ENTITY,
    CONF_PROG5_TIME_START_ENTITY,
    CONF_PROG6_SOC_ENTITY,
    CONF_PROG6_TIME_START_ENTITY,
    CONF_PV_EFFICIENCY,
    CONF_PV_FORECAST_SENSOR,
    CONF_PV_FORECAST_REMAINING,
    CONF_PV_FORECAST_TODAY,
    CONF_PV_FORECAST_TOMORROW,
    CONF_PV_PEAK_FORECAST,
    CONF_TARIFF_END_HOUR_SENSOR,
    CONF_TODAY_LOAD_SENSOR,
    CONF_TOMORROW_PRICE_SENSOR,
    CONF_WEATHER_FORECAST,
    CONF_WORK_MODE_ENTITY,
    CONF_TEST_MODE,
    DEFAULT_BALANCING_INTERVAL_DAYS,
    DEFAULT_BATTERY_CAPACITY_AH,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_BATTERY_VOLTAGE,
    DEFAULT_BALANCING_PV_THRESHOLD,
    DEFAULT_HEAT_PUMP_FORECAST_DOMAIN,
    DEFAULT_HEAT_PUMP_FORECAST_SERVICE,
    DEFAULT_PV_EFFICIENCY,
    DEFAULT_MAX_SOC,
    DEFAULT_MIN_SOC,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class EnergyOptimizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Energy Optimizer."""

    VERSION = 2

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
                ): vol.All(vol.Coerce(float), vol.Range(min=12, max=600)),
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
                vol.Optional(
                    CONF_BALANCING_INTERVAL_DAYS, default=DEFAULT_BALANCING_INTERVAL_DAYS
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
                vol.Optional(
                    CONF_BALANCING_PV_THRESHOLD, default=DEFAULT_BALANCING_PV_THRESHOLD
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=200)),
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
                return await self.async_step_time_programs()

        schema = vol.Schema(
            {
                vol.Optional(CONF_WORK_MODE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="select")
                ),
                vol.Optional(CONF_CHARGE_CURRENT_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(CONF_DISCHARGE_CURRENT_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(CONF_MAX_CHARGE_CURRENT_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(CONF_TEST_MODE, default=True): bool,
                vol.Optional(CONF_GRID_CHARGE_SWITCH): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
            }
        )

        return self.async_show_form(
            step_id="control_entities", data_schema=schema, errors=errors
        )

    async def async_step_time_programs(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle time-based program configuration (optional)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_program_entities(user_input)
            if not errors:
                self._data.update(user_input)
                return await self.async_step_pv_load_config()

        schema = vol.Schema(
            {
                vol.Optional(CONF_PROG1_SOC_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(CONF_PROG1_TIME_START_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["input_datetime", "sensor", "time"])
                ),
                vol.Optional(CONF_PROG2_SOC_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(CONF_PROG2_TIME_START_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["input_datetime", "sensor", "time"])
                ),
                vol.Optional(CONF_PROG3_SOC_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(CONF_PROG3_TIME_START_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["input_datetime", "sensor", "time"])
                ),
                vol.Optional(CONF_PROG4_SOC_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(CONF_PROG4_TIME_START_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["input_datetime", "sensor", "time"])
                ),
                vol.Optional(CONF_PROG5_SOC_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(CONF_PROG5_TIME_START_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["input_datetime", "sensor", "time"])
                ),
                vol.Optional(CONF_PROG6_SOC_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(CONF_PROG6_TIME_START_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["input_datetime", "sensor", "time"])
                ),
            }
        )

        return self.async_show_form(
            step_id="time_programs", data_schema=schema, errors=errors
        )

    async def async_step_pv_load_config(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle PV forecast and load sensor configuration."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_load_windows()

        schema = vol.Schema(
            {
                vol.Optional(CONF_DAILY_LOAD_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_DAILY_LOSSES_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_TARIFF_END_HOUR_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["input_datetime", "sensor", "time"])
                ),
                vol.Optional(CONF_PV_FORECAST_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_PV_EFFICIENCY,
                    default=DEFAULT_PV_EFFICIENCY,
                ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=2.0)),
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

    async def async_step_load_windows(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle time-windowed load sensor configuration."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_heat_pump()

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TODAY_LOAD_SENSOR,
                    description={"suggested_value": "sensor.load_usage_daily"},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_LOAD_USAGE_00_04): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_LOAD_USAGE_04_08): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_LOAD_USAGE_08_12): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_LOAD_USAGE_12_16): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_LOAD_USAGE_16_20): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_LOAD_USAGE_20_24): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
            }
        )

        return self.async_show_form(
            step_id="load_windows",
            data_schema=schema,
            description_placeholders={
                "info": "Configure time-windowed load sensors for more accurate energy calculations. "
                       "These sensors should track average consumption (kWh/h) for each 4-hour period. "
                       "This configuration is optional but highly recommended for better accuracy."
            }
        )

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
                vol.Optional(
                    CONF_HEAT_PUMP_FORECAST_DOMAIN,
                    default=DEFAULT_HEAT_PUMP_FORECAST_DOMAIN,
                ): vol.Coerce(str),
                vol.Optional(
                    CONF_HEAT_PUMP_FORECAST_SERVICE,
                    default=DEFAULT_HEAT_PUMP_FORECAST_SERVICE,
                ): vol.Coerce(str),
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
            "Battery Capacity": f"{self._data.get(CONF_BATTERY_CAPACITY_AH, 0)} Ah",
            "Battery Voltage": f"{self._data.get(CONF_BATTERY_VOLTAGE, 0)} V",
        }

        # Count configured programs
        program_count = sum(
            1 for key in [
                CONF_PROG1_SOC_ENTITY, CONF_PROG2_SOC_ENTITY, CONF_PROG3_SOC_ENTITY,
                CONF_PROG4_SOC_ENTITY, CONF_PROG5_SOC_ENTITY, CONF_PROG6_SOC_ENTITY
            ]
            if self._data.get(key)
        )

        if program_count > 0:
            review_data["Time Programs"] = f"{program_count} configured"

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

        self._validate_entity(
            entity_id=user_input.get(CONF_PRICE_SENSOR),
            field=CONF_PRICE_SENSOR,
            errors=errors,
            value_type=float,
        )
        self._validate_entity(
            entity_id=user_input.get(CONF_AVERAGE_PRICE_SENSOR),
            field=CONF_AVERAGE_PRICE_SENSOR,
            errors=errors,
            value_type=float,
        )

        return errors

    def _validate_entity(
        self,
        *,
        entity_id: str | None,
        field: str,
        errors: dict[str, str],
        value_type: type[float] | type[int] | None = None,
        expected_domain: str | None = None,
        domain_error: str = "not_number_entity",
    ) -> Any | None:
        """Validate an entity from config flow input.

        Populates the config-flow `errors` dict using existing translation keys.
        Returns the coerced value (if `value_type` provided) or `None` if invalid.
        """
        if not entity_id:
            errors[field] = "entity_not_found"
            return None

        state = self.hass.states.get(entity_id)
        if not state:
            errors[field] = "entity_not_found"
            return None

        if expected_domain is not None and state.domain != expected_domain:
            errors[field] = domain_error
            return None

        if value_type is None:
            return state

        if value_type is float:
            if not self._is_numeric_state(state.state):
                errors[field] = "not_numeric"
                return None
            return float(state.state)

        try:
            return value_type(state.state)
        except (ValueError, TypeError):
            errors[field] = "not_numeric"
            return None

    async def _validate_battery_sensors(
        self, user_input: dict[str, Any]
    ) -> dict[str, str]:
        """Validate battery sensor configuration."""
        errors = {}

        self._validate_entity(
            entity_id=user_input.get(CONF_BATTERY_SOC_SENSOR),
            field=CONF_BATTERY_SOC_SENSOR,
            errors=errors,
            value_type=float,
        )
        self._validate_entity(
            entity_id=user_input.get(CONF_BATTERY_POWER_SENSOR),
            field=CONF_BATTERY_POWER_SENSOR,
            errors=errors,
            value_type=float,
        )

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

        # Validate max charge current entity if provided
        max_charge_entity = user_input.get(CONF_MAX_CHARGE_CURRENT_ENTITY)
        if max_charge_entity:
            self._validate_entity(
                entity_id=max_charge_entity,
                field=CONF_MAX_CHARGE_CURRENT_ENTITY,
                errors=errors,
                expected_domain="number",
                domain_error="not_number_entity",
            )

        return errors

    async def _validate_program_entities(
        self, user_input: dict[str, Any]
    ) -> dict[str, str]:
        """Validate time-based program entity configuration."""
        errors = {}

        # Check that at least one targeting method is configured
        has_programs = False

        # Validate each configured program
        program_configs = [
            (CONF_PROG1_SOC_ENTITY, CONF_PROG1_TIME_START_ENTITY),
            (CONF_PROG2_SOC_ENTITY, CONF_PROG2_TIME_START_ENTITY),
            (CONF_PROG3_SOC_ENTITY, CONF_PROG3_TIME_START_ENTITY),
            (CONF_PROG4_SOC_ENTITY, CONF_PROG4_TIME_START_ENTITY),
            (CONF_PROG5_SOC_ENTITY, CONF_PROG5_TIME_START_ENTITY),
            (CONF_PROG6_SOC_ENTITY, CONF_PROG6_TIME_START_ENTITY),
        ]

        for soc_key, start_key in program_configs:
            soc_entity = user_input.get(soc_key)
            start_time = user_input.get(start_key)

            if soc_entity:
                has_programs = True
                self._validate_entity(
                    entity_id=soc_entity,
                    field=soc_key,
                    errors=errors,
                    expected_domain="number",
                    domain_error="not_number_entity",
                )

                # Warn if start time not configured (optional but recommended)
                if not start_time:
                    _LOGGER.warning(
                        "%s configured without start time - will be used for manual control only",
                        soc_key
                    )

        # Ensure at least one targeting method is configured
        if not has_programs:
            errors["base"] = "no_target_configured"

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
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Validate min/max SOC relationship
            if user_input[CONF_MIN_SOC] >= user_input[CONF_MAX_SOC]:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._get_options_schema(),
                    errors={"base": "min_greater_than_max"},
                )
            
            # Update config entry
            self.hass.config_entries.async_update_entry(
                self._config_entry, data={**self._config_entry.data, **user_input}
            )
            options = {**(self._config_entry.options or {})}
            options[CONF_TEST_MODE] = user_input.get(
                CONF_TEST_MODE,
                self._config_entry.data.get(CONF_TEST_MODE, True),
            )
            return self.async_create_entry(title="", data=options)

        return self.async_show_form(step_id="init", data_schema=self._get_options_schema())
    
    def _get_options_schema(self) -> vol.Schema:
        """Get options schema with all parameters for calculate_usable_capacity."""
        return vol.Schema(
            {
                vol.Optional(
                    CONF_BATTERY_CAPACITY_AH,
                    default=self._config_entry.data.get(
                        CONF_BATTERY_CAPACITY_AH, DEFAULT_BATTERY_CAPACITY_AH
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=1, max=1000)),
                vol.Optional(
                    CONF_BATTERY_VOLTAGE,
                    default=self._config_entry.data.get(
                        CONF_BATTERY_VOLTAGE, DEFAULT_BATTERY_VOLTAGE
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=12, max=600)),
                vol.Optional(
                    CONF_MIN_SOC,
                    default=self._config_entry.data.get(CONF_MIN_SOC, DEFAULT_MIN_SOC),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Optional(
                    CONF_MAX_SOC,
                    default=self._config_entry.data.get(CONF_MAX_SOC, DEFAULT_MAX_SOC),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Optional(
                    CONF_BATTERY_EFFICIENCY,
                    default=self._config_entry.data.get(
                        CONF_BATTERY_EFFICIENCY, DEFAULT_BATTERY_EFFICIENCY
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=50, max=100)),
                vol.Optional(
                    CONF_BALANCING_INTERVAL_DAYS,
                    default=self._config_entry.data.get(
                        CONF_BALANCING_INTERVAL_DAYS, DEFAULT_BALANCING_INTERVAL_DAYS
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
                vol.Optional(
                    CONF_BALANCING_PV_THRESHOLD,
                    default=self._config_entry.data.get(
                        CONF_BALANCING_PV_THRESHOLD, DEFAULT_BALANCING_PV_THRESHOLD
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=200)),
                vol.Optional(
                    CONF_DAILY_LOSSES_SENSOR,
                    default=self._config_entry.data.get(CONF_DAILY_LOSSES_SENSOR)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_TARIFF_END_HOUR_SENSOR,
                    default=self._config_entry.data.get(CONF_TARIFF_END_HOUR_SENSOR)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["input_datetime", "sensor", "time"])
                ),
                vol.Optional(
                    CONF_TODAY_LOAD_SENSOR,
                    default=self._config_entry.data.get(CONF_TODAY_LOAD_SENSOR)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_LOAD_USAGE_00_04,
                    default=self._config_entry.data.get(CONF_LOAD_USAGE_00_04)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_LOAD_USAGE_04_08,
                    default=self._config_entry.data.get(CONF_LOAD_USAGE_04_08)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_LOAD_USAGE_08_12,
                    default=self._config_entry.data.get(CONF_LOAD_USAGE_08_12)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_LOAD_USAGE_12_16,
                    default=self._config_entry.data.get(CONF_LOAD_USAGE_12_16)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_LOAD_USAGE_16_20,
                    default=self._config_entry.data.get(CONF_LOAD_USAGE_16_20)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_LOAD_USAGE_20_24,
                    default=self._config_entry.data.get(CONF_LOAD_USAGE_20_24)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_MAX_CHARGE_CURRENT_ENTITY,
                    default=self._config_entry.data.get(
                        CONF_MAX_CHARGE_CURRENT_ENTITY
                    ),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(
                    CONF_ENABLE_HEAT_PUMP,
                    default=self._config_entry.data.get(CONF_ENABLE_HEAT_PUMP, False),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_HEAT_PUMP_FORECAST_DOMAIN,
                    default=self._config_entry.data.get(
                        CONF_HEAT_PUMP_FORECAST_DOMAIN, DEFAULT_HEAT_PUMP_FORECAST_DOMAIN
                    ),
                ): vol.Coerce(str),
                vol.Optional(
                    CONF_HEAT_PUMP_FORECAST_SERVICE,
                    default=self._config_entry.data.get(
                        CONF_HEAT_PUMP_FORECAST_SERVICE, DEFAULT_HEAT_PUMP_FORECAST_SERVICE
                    ),
                ): vol.Coerce(str),
                vol.Optional(
                    CONF_TEST_MODE,
                    default=(self._config_entry.options or {}).get(
                        CONF_TEST_MODE,
                        self._config_entry.data.get(CONF_TEST_MODE, True),
                    ),
                ): bool,
            }
        )
