"""Service handlers for Energy Optimizer integration."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING

from homeassistant.core import ServiceCall
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def check_and_update_balancing_completion(hass: HomeAssistant, entry) -> None:
    """Check if battery has been above 97% SOC for 2+ hours and update balancing timestamp.
    
    This function should be called periodically (e.g., every 5 minutes) to monitor
    battery SOC and determine if balancing has been successfully completed.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
    """
    from .const import CONF_BATTERY_SOC_SENSOR, DOMAIN
    
    config = entry.data
    
    # Get battery SOC sensor
    soc_sensor = config.get(CONF_BATTERY_SOC_SENSOR)
    if not soc_sensor:
        return
    
    soc_state = hass.states.get(soc_sensor)
    if not soc_state or soc_state.state in ("unknown", "unavailable"):
        return
    
    try:
        current_soc = float(soc_state.state)
    except (ValueError, TypeError):
        return
    
    # Get last balancing sensor
    last_balancing_sensor = None
    if (
        DOMAIN in hass.data
        and entry.entry_id in hass.data[DOMAIN]
        and isinstance(hass.data[DOMAIN][entry.entry_id], dict)
        and "last_balancing_sensor" in hass.data[DOMAIN][entry.entry_id]
    ):
        last_balancing_sensor = hass.data[DOMAIN][entry.entry_id]["last_balancing_sensor"]
    
    if not last_balancing_sensor:
        return
    
    # Check if SOC is above 97%
    if current_soc >= 97.0:
        # Get or initialize the high SOC tracking attribute
        attrs = last_balancing_sensor.extra_state_attributes or {}
        high_soc_start = attrs.get("high_soc_start_time")
        
        if not high_soc_start:
            # First time above 97%, record the timestamp
            high_soc_start = dt_util.utcnow()
            last_balancing_sensor._attr_extra_state_attributes = {
                **attrs,
                "high_soc_start_time": high_soc_start.isoformat(),
            }
            last_balancing_sensor.async_write_ha_state()
            _LOGGER.debug("Battery SOC reached 97%%, starting 2-hour monitoring")
        else:
            # SOC has been above 97% for some time, check duration
            if isinstance(high_soc_start, str):
                high_soc_start = datetime.fromisoformat(high_soc_start)
            
            duration = dt_util.utcnow() - high_soc_start
            hours_at_high_soc = duration.total_seconds() / 3600
            
            if hours_at_high_soc >= 2.0:
                # Battery has been above 97% for 2+ hours, update balancing timestamp
                _LOGGER.info(
                    "Battery balancing completed: SOC %.1f%% for %.1f hours",
                    current_soc,
                    hours_at_high_soc,
                )
                last_balancing_sensor.update_balancing_timestamp()
                
                # Clear the tracking attribute
                last_balancing_sensor._attr_extra_state_attributes = {
                    k: v for k, v in attrs.items() if k != "high_soc_start_time"
                }
                last_balancing_sensor.async_write_ha_state()
                
                # Log to optimization sensors
                if "last_optimization_sensor" in hass.data[DOMAIN][entry.entry_id]:
                    opt_sensor = hass.data[DOMAIN][entry.entry_id]["last_optimization_sensor"]
                    opt_sensor.log_optimization(
                        "Balancing Completed",
                        {
                            "final_soc": round(current_soc, 1),
                            "duration_hours": round(hours_at_high_soc, 1),
                        },
                    )
            else:
                _LOGGER.debug(
                    "Battery at %.1f%% for %.1f hours (need 2.0 hours)",
                    current_soc,
                    hours_at_high_soc,
                )
    else:
        # SOC dropped below 97%, reset tracking
        attrs = last_balancing_sensor.extra_state_attributes or {}
        if "high_soc_start_time" in attrs:
            _LOGGER.debug(
                "Battery SOC dropped below 97%% (now %.1f%%), resetting tracking",
                current_soc,
            )
            last_balancing_sensor._attr_extra_state_attributes = {
                k: v for k, v in attrs.items() if k != "high_soc_start_time"
            }
            last_balancing_sensor.async_write_ha_state()


async def async_register_services(hass: HomeAssistant) -> None:
    """Register all services for the Energy Optimizer integration.
    
    Args:
        hass: Home Assistant instance
    """
    from .const import (
        DOMAIN,
        SERVICE_CALCULATE_CHARGE_SOC,
        SERVICE_CALCULATE_SELL_ENERGY,
        SERVICE_ESTIMATE_HEAT_PUMP,
        SERVICE_OVERNIGHT_SCHEDULE,
    )
    from .helpers import get_active_program_entity

    async def handle_calculate_charge_soc(call: ServiceCall) -> None:
        """Handle calculate_charge_soc service call."""
        from .calculations.battery import (
            calculate_battery_space,
            kwh_to_soc,
            soc_to_kwh,
        )
        from .calculations.energy import calculate_required_energy, calculate_required_energy_windowed
        from .const import (
            CONF_LOAD_USAGE_00_04,
            CONF_LOAD_USAGE_04_08,
            CONF_LOAD_USAGE_08_12,
            CONF_LOAD_USAGE_12_16,
            CONF_LOAD_USAGE_16_20,
            CONF_LOAD_USAGE_20_24,
        )

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
            efficiency = config.get("battery_efficiency", 95)

            # Calculate required energy using time-windowed data if available
            now = datetime.now()
            hours_until_end = call.data.get("hours_until_end", 12)
            end_hour = (now.hour + hours_until_end) % 24
            include_tomorrow = (now.hour + hours_until_end) >= 24
            
            # Check if windowed config available
            has_windowed = any(
                config.get(key)
                for key in [
                    CONF_LOAD_USAGE_00_04, CONF_LOAD_USAGE_04_08,
                    CONF_LOAD_USAGE_08_12, CONF_LOAD_USAGE_12_16,
                    CONF_LOAD_USAGE_16_20, CONF_LOAD_USAGE_20_24,
                ]
            )
            
            if has_windowed:
                try:
                    required_energy = calculate_required_energy_windowed(
                        start_hour=now.hour,
                        end_hour=end_hour,
                        config=config,
                        hass_states_get=hass.states.get,
                        efficiency=efficiency,
                        include_tomorrow=include_tomorrow,
                        current_hour=now.hour,
                        current_minute=now.minute,
                    )
                    _LOGGER.debug("Using time-windowed calculation: %.2f kWh", required_energy)
                except Exception as ex:
                    _LOGGER.warning("Time-windowed calculation failed, using fallback: %s", ex)
                    required_energy = calculate_required_energy(
                        hourly_usage=2.0, hourly_losses=0,
                        hours=hours_until_end, efficiency=efficiency / 100.0
                    )
            else:
                # Fallback to simplified calculation
                required_energy = calculate_required_energy(
                    hourly_usage=2.0, hourly_losses=0,
                    hours=hours_until_end, efficiency=efficiency / 100.0
                )
                _LOGGER.debug("Using simple calculation (no time windows): %.2f kWh", required_energy)

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

            # Determine which SOC entity to update (program-aware or single entity)
            target_entity = None
            
            # First, try to find active program entity
            current_time = datetime.now()
            program_entity = get_active_program_entity(hass, config, current_time)
            
            if program_entity:
                target_entity = program_entity
                _LOGGER.info("Using program entity: %s", program_entity)
            else:
                # Fall back to single target entity
                target_entity = config.get("target_soc_entity")
                if target_entity:
                    _LOGGER.info("Using single target entity: %s", target_entity)
                else:
                    _LOGGER.warning("No target SOC entity configured (neither program nor single)")
            
            # Write target SOC to the determined entity
            if target_entity:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": target_entity, "value": target_soc},
                    blocking=True,
                )
                _LOGGER.info(
                    "Set %s to %s%% (current: %s%%, charge energy: %.2f kWh)",
                    target_entity,
                    target_soc,
                    current_soc,
                    charge_energy,
                )
            else:
                _LOGGER.info(
                    "Calculated charge target: %s%% (current: %s%%, energy: %.2f kWh) - no entity to update",
                    target_soc,
                    current_soc,
                    charge_energy,
                )

        except (ValueError, TypeError) as err:
            _LOGGER.error("Error calculating charge SOC: %s", err)

    async def handle_calculate_sell_energy(call: ServiceCall) -> None:
        """Handle calculate_sell_energy service call."""
        from .calculations.battery import calculate_battery_reserve
        from .calculations.energy import calculate_required_energy, calculate_required_energy_windowed, calculate_surplus_energy
        from .const import (
            CONF_LOAD_USAGE_00_04,
            CONF_LOAD_USAGE_04_08,
            CONF_LOAD_USAGE_08_12,
            CONF_LOAD_USAGE_12_16,
            CONF_LOAD_USAGE_16_20,
            CONF_LOAD_USAGE_20_24,
        )

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
            efficiency = config.get("battery_efficiency", 95)

            # Calculate available reserve
            battery_reserve = calculate_battery_reserve(
                current_soc, min_soc, capacity_ah, voltage
            )

            # Calculate required energy using time-windowed data if available
            now = datetime.now()
            hours_remaining = call.data.get("hours_remaining", 4)
            end_hour = (now.hour + hours_remaining) % 24
            include_tomorrow = (now.hour + hours_remaining) >= 24
            
            # Check if windowed config available
            has_windowed = any(
                config.get(key)
                for key in [
                    CONF_LOAD_USAGE_00_04, CONF_LOAD_USAGE_04_08,
                    CONF_LOAD_USAGE_08_12, CONF_LOAD_USAGE_12_16,
                    CONF_LOAD_USAGE_16_20, CONF_LOAD_USAGE_20_24,
                ]
            )
            
            if has_windowed:
                try:
                    required_energy = calculate_required_energy_windowed(
                        start_hour=now.hour,
                        end_hour=end_hour,
                        config=config,
                        hass_states_get=hass.states.get,
                        efficiency=efficiency,
                        include_tomorrow=include_tomorrow,
                        current_hour=now.hour,
                        current_minute=now.minute,
                    )
                    _LOGGER.debug("Using time-windowed calculation: %.2f kWh", required_energy)
                except Exception as ex:
                    _LOGGER.warning("Time-windowed calculation failed, using fallback: %s", ex)
                    required_energy = calculate_required_energy(
                        hourly_usage=2.0, hourly_losses=0,
                        hours=hours_remaining, efficiency=efficiency / 100.0
                    )
            else:
                # Fallback to simplified calculation
                required_energy = calculate_required_energy(
                    hourly_usage=2.0, hourly_losses=0,
                    hours=hours_remaining, efficiency=efficiency / 100.0
                )
                _LOGGER.debug("Using simple calculation (no time windows): %.2f kWh", required_energy)

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

    async def handle_overnight_schedule(call: ServiceCall) -> None:
        """Handle overnight_schedule service call."""
        _LOGGER.info("=== Battery Overnight Handling Started ===")
        
        from .calculations.battery import calculate_battery_space
        from .const import (
            CONF_BALANCING_INTERVAL_DAYS,
            CONF_BALANCING_PV_THRESHOLD,
            CONF_BATTERY_SOC_SENSOR,
            CONF_MAX_CHARGE_CURRENT_ENTITY,
            CONF_PROG1_SOC_ENTITY,
            CONF_PROG6_SOC_ENTITY,
            CONF_PV_FORECAST_TOMORROW,
            DEFAULT_BALANCING_INTERVAL_DAYS,
            DEFAULT_BALANCING_PV_THRESHOLD,
        )

        # Get configuration
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No Energy Optimizer configuration found")
            return

        entry = entries[0]
        config = entry.data

        # Get sensor reference from hass.data
        last_balancing_sensor = None
        if (
            DOMAIN in hass.data
            and entry.entry_id in hass.data[DOMAIN]
            and isinstance(hass.data[DOMAIN][entry.entry_id], dict)
            and "last_balancing_sensor" in hass.data[DOMAIN][entry.entry_id]
        ):
            last_balancing_sensor = hass.data[DOMAIN][entry.entry_id]["last_balancing_sensor"]
        else:
            _LOGGER.warning(
                "Last balancing sensor not yet initialized. "
                "Balancing timestamp will not be updated this run."
            )

        # Read configuration
        balancing_interval_days = config.get(
            CONF_BALANCING_INTERVAL_DAYS, DEFAULT_BALANCING_INTERVAL_DAYS
        )
        balancing_pv_threshold = config.get(
            CONF_BALANCING_PV_THRESHOLD, DEFAULT_BALANCING_PV_THRESHOLD
        )

        # Check if balancing is due
        last_balancing = (
            last_balancing_sensor.native_value if last_balancing_sensor else None
        )
        days_since_balancing = None
        if last_balancing:
            days_since_balancing = (dt_util.utcnow() - last_balancing).days
            _LOGGER.debug(
                "Days since last balancing: %s (last: %s)",
                days_since_balancing,
                last_balancing,
            )

        balancing_due = (last_balancing is None) or (
            days_since_balancing >= balancing_interval_days
        )

        # Get PV forecast
        pv_forecast_entity = config.get(CONF_PV_FORECAST_TOMORROW)
        pv_forecast = 0.0
        if pv_forecast_entity:
            pv_state = hass.states.get(pv_forecast_entity)
            if pv_state and pv_state.state not in ("unknown", "unavailable"):
                try:
                    pv_forecast = float(pv_state.state)
                except (ValueError, TypeError) as err:
                    _LOGGER.warning("Could not parse PV forecast: %s", err)

        _LOGGER.debug(
            "Balancing check: due=%s, pv_forecast=%.2f kWh, threshold=%.2f kWh",
            balancing_due,
            pv_forecast,
            balancing_pv_threshold,
        )

        # SCENARIO 1: Battery Balancing Mode
        if balancing_due and pv_forecast < balancing_pv_threshold:
            _LOGGER.info(
                "Activating battery balancing mode (PV forecast: %.2f kWh < %.2f kWh)",
                pv_forecast,
                balancing_pv_threshold,
            )

            # Set program SOC targets to 100%
            prog1_soc = config.get(CONF_PROG1_SOC_ENTITY)
            prog6_soc = config.get(CONF_PROG6_SOC_ENTITY)
            max_charge_current = config.get(CONF_MAX_CHARGE_CURRENT_ENTITY)

            if prog1_soc:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": prog1_soc, "value": 100},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to 100%%", prog1_soc)

            if prog6_soc:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": prog6_soc, "value": 100},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to 100%%", prog6_soc)

            if max_charge_current:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": max_charge_current, "value": 23},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to 23A", max_charge_current)

            # Note: Balancing timestamp will be updated automatically
            # when SOC stays above 97% for 2+ hours (checked in check_and_update_balancing_completion)

            # Log to optimization sensors
            if "last_optimization_sensor" in hass.data[DOMAIN][entry.entry_id]:
                opt_sensor = hass.data[DOMAIN][entry.entry_id]["last_optimization_sensor"]
                opt_sensor.log_optimization(
                    "Battery Balancing",
                    {
                        "pv_forecast_kwh": round(pv_forecast, 2),
                        "threshold_kwh": balancing_pv_threshold,
                        "target_soc": 100,
                        "days_since_last": days_since_balancing,
                    },
                )
            if "optimization_history_sensor" in hass.data[DOMAIN][entry.entry_id]:
                hist_sensor = hass.data[DOMAIN][entry.entry_id]["optimization_history_sensor"]
                hist_sensor.add_entry(
                    "Battery Balancing",
                    {
                        "pv_forecast": f"{pv_forecast:.1f} kWh",
                        "target": "100%",
                        "reason": f"Low PV forecast ({pv_forecast:.1f} < {balancing_pv_threshold:.1f})",
                    },
                )

            # Send notification
            await hass.services.async_call(
                "notify",
                "notify",
                {"message": "Night battery balancing enabled - Up to 100%"},
                blocking=False,
            )

            _LOGGER.info("Battery balancing mode activated")
            return

        # Get current battery SOC for preservation scenarios
        _LOGGER.debug("Balancing not triggered - checking preservation/normal operation modes")
        soc_sensor = config.get(CONF_BATTERY_SOC_SENSOR)
        current_soc = None
        if soc_sensor:
            soc_state = hass.states.get(soc_sensor)
            if soc_state and soc_state.state not in ("unknown", "unavailable"):
                try:
                    current_soc = float(soc_state.state)
                except (ValueError, TypeError) as err:
                    _LOGGER.warning("Could not parse battery SOC: %s", err)

        if current_soc is None:
            _LOGGER.warning("Current battery SOC not available, skipping preservation check")
            return

        # Calculate battery space
        capacity_ah = config.get("battery_capacity_ah", 200)
        voltage = config.get("battery_voltage", 48)
        max_soc = config.get("max_soc", 100)

        battery_space = calculate_battery_space(current_soc, max_soc, capacity_ah, voltage)
        pv_with_efficiency = pv_forecast * 0.9  # 90% efficiency factor

        _LOGGER.debug(
            "Battery space: %.2f kWh, PV forecast (90%%): %.2f kWh",
            battery_space,
            pv_with_efficiency,
        )

        # SCENARIO 2: Battery Preservation Mode
        if pv_with_efficiency < battery_space:
            _LOGGER.info(
                "Activating battery preservation mode (PV %.2f kWh < space %.2f kWh)",
                pv_with_efficiency,
                battery_space,
            )

            prog1_soc = config.get(CONF_PROG1_SOC_ENTITY)
            prog6_soc = config.get(CONF_PROG6_SOC_ENTITY)

            # Lock battery at current SOC to avoid inefficient charge/discharge cycles
            # When tomorrow's PV is too low to justify battery usage today
            if prog1_soc:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": prog1_soc, "value": current_soc},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to %.1f%% (current SOC)", prog1_soc, current_soc)

            if prog6_soc:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": prog6_soc, "value": current_soc},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to %.1f%% (current SOC)", prog6_soc, current_soc)

            # Log to optimization sensors
            if "last_optimization_sensor" in hass.data[DOMAIN][entry.entry_id]:
                opt_sensor = hass.data[DOMAIN][entry.entry_id]["last_optimization_sensor"]
                opt_sensor.log_optimization(
                    "Battery Preservation",
                    {
                        "pv_forecast_kwh": round(pv_forecast, 2),
                        "pv_with_efficiency_kwh": round(pv_with_efficiency, 2),
                        "battery_space_kwh": round(battery_space, 2),
                        "locked_soc": round(current_soc, 1),
                    },
                )
            if "optimization_history_sensor" in hass.data[DOMAIN][entry.entry_id]:
                hist_sensor = hass.data[DOMAIN][entry.entry_id]["optimization_history_sensor"]
                hist_sensor.add_entry(
                    "Battery Preservation",
                    {
                        "pv_forecast": f"{pv_forecast:.1f} kWh",
                        "battery_space": f"{battery_space:.1f} kWh",
                        "locked_at": f"{current_soc:.0f}%",
                        "reason": f"PV too low for battery space ({pv_with_efficiency:.1f} < {battery_space:.1f})",
                    },
                )

            # Send notification
            await hass.services.async_call(
                "notify",
                "notify",
                {
                    "message": f"Battery preservation mode - SOC locked at {current_soc:.0f}%"
                },
                blocking=False,
            )

            _LOGGER.info("Battery preservation mode activated")
            return

        # SCENARIO 3: Normal Operation Restoration
        _LOGGER.debug("Preservation not needed - checking normal operation restoration")
        prog6_soc = config.get(CONF_PROG6_SOC_ENTITY)
        min_soc = config.get("min_soc", 15)

        current_prog6_soc = None
        if prog6_soc:
            prog6_state = hass.states.get(prog6_soc)
            if prog6_state and prog6_state.state not in ("unknown", "unavailable"):
                try:
                    current_prog6_soc = float(prog6_state.state)
                except (ValueError, TypeError) as err:
                    _LOGGER.warning("Could not parse prog6 SOC: %s", err)

        if (
            current_prog6_soc is not None
            and current_prog6_soc > min_soc
            and not (pv_with_efficiency < battery_space)
        ):
            _LOGGER.info(
                "Restoring normal operation (current: %.0f%%, restoring to: %.0f%%)",
                current_prog6_soc,
                min_soc,
            )

            prog1_soc = config.get(CONF_PROG1_SOC_ENTITY)

            if prog1_soc:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": prog1_soc, "value": min_soc},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to %.0f%%", prog1_soc, min_soc)

            if prog6_soc:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": prog6_soc, "value": min_soc},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to %.0f%%", prog6_soc, min_soc)

            # Log to optimization sensors
            if "last_optimization_sensor" in hass.data[DOMAIN][entry.entry_id]:
                opt_sensor = hass.data[DOMAIN][entry.entry_id]["last_optimization_sensor"]
                opt_sensor.log_optimization(
                    "Normal Operation Restored",
                    {
                        "previous_soc": round(current_prog6_soc, 1),
                        "restored_to_soc": min_soc,
                        "pv_forecast_kwh": round(pv_forecast, 2),
                    },
                )
            if "optimization_history_sensor" in hass.data[DOMAIN][entry.entry_id]:
                hist_sensor = hass.data[DOMAIN][entry.entry_id]["optimization_history_sensor"]
                hist_sensor.add_entry(
                    "Normal Operation",
                    {
                        "previous": f"{current_prog6_soc:.0f}%",
                        "restored_to": f"{min_soc:.0f}%",
                        "reason": "PV within normal range",
                    },
                )

            # Send notification
            await hass.services.async_call(
                "notify",
                "notify",
                {"message": f"Normal battery operation restored - SOC minimum {min_soc:.0f}%"},
                blocking=False,
            )

            _LOGGER.info("Normal operation restored")
            return

        # Log when no action taken
        if "last_optimization_sensor" in hass.data[DOMAIN][entry.entry_id]:
            opt_sensor = hass.data[DOMAIN][entry.entry_id]["last_optimization_sensor"]
            opt_sensor.log_optimization(
                "No Action",
                {
                    "pv_forecast_kwh": round(pv_forecast, 2),
                    "battery_space_kwh": round(battery_space, 2) if battery_space else 0,
                    "current_soc": round(current_soc, 1) if current_soc else 0,
                },
            )
        if "optimization_history_sensor" in hass.data[DOMAIN][entry.entry_id]:
            hist_sensor = hass.data[DOMAIN][entry.entry_id]["optimization_history_sensor"]
            hist_sensor.add_entry(
                "No Action",
                {"reason": "No changes needed"},
            )

        _LOGGER.debug("No battery schedule changes needed")

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
        DOMAIN, SERVICE_OVERNIGHT_SCHEDULE, handle_overnight_schedule
    )

    _LOGGER.info("Energy Optimizer services registered")
