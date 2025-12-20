"""The Energy Optimizer integration."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    SERVICE_CALCULATE_CHARGE_SOC,
    SERVICE_CALCULATE_SELL_ENERGY,
    SERVICE_ESTIMATE_HEAT_PUMP,
    SERVICE_OPTIMIZE_SCHEDULE,
)

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Energy Optimizer component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Optimizer from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Forward entry setup to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (only once, not per config entry)
    if not hass.services.has_service(DOMAIN, SERVICE_CALCULATE_CHARGE_SOC):
        await async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register Energy Optimizer services."""

    async def handle_calculate_charge_soc(call: ServiceCall) -> None:
        """Handle calculate_charge_soc service call."""
        from .calculations.battery import (
            calculate_battery_space,
            kwh_to_soc,
            soc_to_kwh,
        )
        from .calculations.energy import calculate_required_energy

        # Get config entry (use first one if multiple exist)
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No Energy Optimizer configuration found")
            return

        config = entries[0].data

        # Read current states
        price_state = hass.states.get(config.get("price_sensor"))
        avg_price_state = hass.states.get(config.get("average_price_sensor"))
        soc_state = hass.states.get(config.get("battery_soc_sensor"))

        if not all([price_state, avg_price_state, soc_state]):
            _LOGGER.error("Required sensor states not available")
            return

        try:
            current_price = float(price_state.state)
            avg_price = float(avg_price_state.state)
            current_soc = float(soc_state.state)

            # Get battery parameters
            capacity_ah = config.get("battery_capacity_ah", 200)
            voltage = config.get("battery_voltage", 48)
            max_soc = config.get("max_soc", 100)

            # Calculate required energy (simplified for now)
            # TODO: Integrate with load history and PV forecast
            required_energy = calculate_required_energy(
                hourly_usage=2.0, hours=12, efficiency=0.95
            )

            # Determine if we should charge based on price
            if current_price < avg_price * 0.8:  # Charge if price is 20% below average
                # Calculate available space
                battery_space = calculate_battery_space(
                    current_soc, max_soc, capacity_ah, voltage
                )

                # Target full charge if cheap
                target_soc = max_soc
                charge_energy = battery_space
            else:
                # Just charge enough for requirements
                target_soc = min(
                    current_soc + kwh_to_soc(required_energy, capacity_ah, voltage),
                    max_soc,
                )
                charge_energy = soc_to_kwh(target_soc - current_soc, capacity_ah, voltage)

            # Write target SOC to control entity
            target_soc_entity = config.get("target_soc_entity")
            if target_soc_entity:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": target_soc_entity, "value": target_soc},
                    blocking=True,
                )

            _LOGGER.info(
                "Calculated charge target: %s%% (current: %s%%, energy: %s kWh)",
                target_soc,
                current_soc,
                charge_energy,
            )

        except (ValueError, TypeError) as err:
            _LOGGER.error("Error calculating charge SOC: %s", err)

    async def handle_calculate_sell_energy(call: ServiceCall) -> None:
        """Handle calculate_sell_energy service call."""
        from .calculations.battery import calculate_battery_reserve
        from .calculations.energy import calculate_surplus_energy

        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No Energy Optimizer configuration found")
            return

        config = entries[0].data

        soc_state = hass.states.get(config.get("battery_soc_sensor"))
        if not soc_state:
            _LOGGER.error("Battery SOC sensor not available")
            return

        try:
            current_soc = float(soc_state.state)
            capacity_ah = config.get("battery_capacity_ah", 200)
            voltage = config.get("battery_voltage", 48)
            min_soc = config.get("min_soc", 10)

            # Calculate available reserve
            battery_reserve = calculate_battery_reserve(
                current_soc, min_soc, capacity_ah, voltage
            )

            # Calculate required energy (simplified)
            required_energy = calculate_required_energy(
                hourly_usage=2.0, hours=4, efficiency=0.95
            )

            # Calculate surplus
            surplus = calculate_surplus_energy(battery_reserve, required_energy)

            _LOGGER.info(
                "Calculated sell energy: %s kWh (reserve: %s kWh, required: %s kWh)",
                surplus,
                battery_reserve,
                required_energy,
            )

        except (ValueError, TypeError) as err:
            _LOGGER.error("Error calculating sell energy: %s", err)

    async def handle_estimate_heat_pump(call: ServiceCall) -> None:
        """Handle estimate_heat_pump_usage service call."""
        from .calculations.heat_pump import estimate_daily_consumption
        from .const import DEFAULT_COP_CURVE

        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No Energy Optimizer configuration found")
            return

        config = entries[0].data

        if not config.get("enable_heat_pump", False):
            _LOGGER.warning("Heat pump estimation not enabled")
            return

        temp_sensor = config.get("outside_temp_sensor")
        if temp_sensor:
            temp_state = hass.states.get(temp_sensor)
            if temp_state:
                try:
                    current_temp = float(temp_state.state)
                    # Simplified: use current temp as average
                    consumption = estimate_daily_consumption(
                        min_temp=current_temp - 5,
                        max_temp=current_temp + 5,
                        avg_temp=current_temp,
                        cop_curve=DEFAULT_COP_CURVE,
                    )

                    _LOGGER.info(
                        "Estimated heat pump daily consumption: %s kWh at %s°C",
                        consumption,
                        current_temp,
                    )

                except (ValueError, TypeError) as err:
                    _LOGGER.error("Error estimating heat pump usage: %s", err)

    async def handle_optimize_schedule(call: ServiceCall) -> None:
        """Handle optimize_battery_schedule service call."""
        # TODO: Implement comprehensive schedule optimization
        _LOGGER.info("Battery schedule optimization called (not yet implemented)")

    # Register services
    hass.services.async_register(
        DOMAIN, SERVICE_CALCULATE_CHARGE_SOC, handle_calculate_charge_soc
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CALCULATE_SELL_ENERGY, handle_calculate_sell_energy
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ESTIMATE_HEAT_PUMP, handle_estimate_heat_pump
    )
    hass.services.async_register(
        DOMAIN, SERVICE_OPTIMIZE_SCHEDULE, handle_optimize_schedule
    )

    _LOGGER.info("Energy Optimizer services registered")
