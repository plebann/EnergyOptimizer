"""The Energy Optimizer integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_change

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
    hass.data[DOMAIN].setdefault(entry.entry_id, {})

    # Forward entry setup to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (only once, not per config entry)
    if not hass.services.has_service(DOMAIN, SERVICE_CALCULATE_CHARGE_SOC):
        await async_register_services(hass)

    # Register automatic daily schedule optimization at 22:00
    async def _trigger_optimize_schedule(now):
        """Trigger battery schedule optimization at 22:00."""
        _LOGGER.info("Auto-triggering battery schedule optimization at 22:00")
        await hass.services.async_call(
            DOMAIN,
            SERVICE_OPTIMIZE_SCHEDULE,
            {},
            blocking=False,
        )

    # Track time change: trigger at 22:00 every day
    remove_listener = async_track_time_change(
        hass, _trigger_optimize_schedule, hour=22, minute=0, second=0
    )

    # Store removal callback for cleanup
    if "listeners" not in hass.data[DOMAIN][entry.entry_id]:
        hass.data[DOMAIN][entry.entry_id]["listeners"] = []
    hass.data[DOMAIN][entry.entry_id]["listeners"].append(remove_listener)

    _LOGGER.info("Energy Optimizer: Automatic 22:00 schedule optimization enabled")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Remove time-based listeners
        entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
        for remove_listener in entry_data.get("listeners", []):
            remove_listener()

        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


def get_active_program_entity(
    config: dict[str, Any], current_time: datetime
) -> str | None:
    """Determine which program SOC entity should be updated based on time.
    
    Args:
        config: Configuration dictionary containing program entities and time windows
        current_time: Current datetime to check against time windows
        
    Returns:
        Entity ID of the active program, or None if no programs configured or no match
    """
    from datetime import time as dt_time
    from .const import (
        CONF_PROG1_SOC_ENTITY, CONF_PROG1_TIME_START,
        CONF_PROG2_SOC_ENTITY, CONF_PROG2_TIME_START,
        CONF_PROG3_SOC_ENTITY, CONF_PROG3_TIME_START,
        CONF_PROG4_SOC_ENTITY, CONF_PROG4_TIME_START,
        CONF_PROG5_SOC_ENTITY, CONF_PROG5_TIME_START,
        CONF_PROG6_SOC_ENTITY, CONF_PROG6_TIME_START,
    )
    
    programs = [
        (CONF_PROG1_SOC_ENTITY, CONF_PROG1_TIME_START),
        (CONF_PROG2_SOC_ENTITY, CONF_PROG2_TIME_START),
        (CONF_PROG3_SOC_ENTITY, CONF_PROG3_TIME_START),
        (CONF_PROG4_SOC_ENTITY, CONF_PROG4_TIME_START),
        (CONF_PROG5_SOC_ENTITY, CONF_PROG5_TIME_START),
        (CONF_PROG6_SOC_ENTITY, CONF_PROG6_TIME_START),
    ]
    
    # Build list of configured programs with their start times
    configured_programs = []
    for soc_key, start_key in programs:
        soc_entity = config.get(soc_key)
        start_time = config.get(start_key)
        
        if not soc_entity or not start_time:
            continue
            
        try:
            # Convert time to dt_time object
            if isinstance(start_time, str):
                start_parts = start_time.split(":")
                start_dt = dt_time(int(start_parts[0]), int(start_parts[1]))
            elif isinstance(start_time, dt_time):
                start_dt = start_time
            else:
                _LOGGER.warning("Invalid start_time format for %s: %s", soc_key, start_time)
                continue
                
            configured_programs.append((soc_entity, start_dt))
        except (ValueError, AttributeError, IndexError) as err:
            _LOGGER.warning("Error parsing time for %s: %s", soc_key, err)
            continue
    
    if not configured_programs:
        _LOGGER.debug("No programs configured")
        return None
    
    # Sort programs by start time
    configured_programs.sort(key=lambda x: x[1])
    
    current_time_only = current_time.time()
    
    # Find the active program (current time >= program start and < next program start)
    for i, (soc_entity, start_dt) in enumerate(configured_programs):
        # Get next program's start time (or wrap to first program)
        next_start = configured_programs[(i + 1) % len(configured_programs)][1]
        
        # Check if current time is within this program's window
        if start_dt <= next_start:
            # Normal case: program runs within same day
            if start_dt <= current_time_only < next_start:
                _LOGGER.debug(
                    "Current time %s matches program starting at %s (until %s)",
                    current_time_only, start_dt, next_start
                )
                return soc_entity
        else:
            # Window crosses midnight
            if current_time_only >= start_dt or current_time_only < next_start:
                _LOGGER.debug(
                    "Current time %s matches program starting at %s (until %s, crosses midnight)",
                    current_time_only, start_dt, next_start
                )
                return soc_entity
    
    _LOGGER.debug("No active program found for current time %s", current_time_only)
    return None


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

            # Determine which SOC entity to update (program-aware or single entity)
            target_entity = None
            
            # First, try to find active program entity
            current_time = datetime.now()
            program_entity = get_active_program_entity(config, current_time)
            
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
        from datetime import datetime

        from homeassistant.util import dt as dt_util

        from .calculations.battery import calculate_battery_space
        from .const import (
            CONF_BALANCING_INTERVAL_DAYS,
            CONF_BALANCING_PV_THRESHOLD,
            CONF_BATTERY_SOC_SENSOR,
            CONF_MAX_CHARGE_CURRENT_ENTITY,
            CONF_PROGRAM_MORNING_SOC_ENTITY,
            CONF_PROGRAM_NIGHT_SOC_ENTITY,
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
            program_morning_soc = config.get(CONF_PROGRAM_MORNING_SOC_ENTITY)
            program_night_soc = config.get(CONF_PROGRAM_NIGHT_SOC_ENTITY)
            max_charge_current = config.get(CONF_MAX_CHARGE_CURRENT_ENTITY)

            if program_morning_soc:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": program_morning_soc, "value": 100},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to 100%%", program_morning_soc)

            if program_night_soc:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": program_night_soc, "value": 100},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to 100%%", program_night_soc)

            if max_charge_current:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": max_charge_current, "value": 23},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to 23A", max_charge_current)

            # Update balancing timestamp
            if last_balancing_sensor:
                last_balancing_sensor.update_balancing_timestamp()
            else:
                _LOGGER.warning("Cannot update balancing timestamp - sensor not available")

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
        if pv_with_efficiency > battery_space:
            _LOGGER.info(
                "Activating battery preservation mode (PV %.2f kWh > space %.2f kWh)",
                pv_with_efficiency,
                battery_space,
            )

            program_morning_soc = config.get(CONF_PROGRAM_MORNING_SOC_ENTITY)
            program_night_soc = config.get(CONF_PROGRAM_NIGHT_SOC_ENTITY)

            # Set targets to current SOC to prevent discharge
            if program_morning_soc:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": program_morning_soc, "value": current_soc},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to %.1f%% (current SOC)", program_morning_soc, current_soc)

            if program_night_soc:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": program_night_soc, "value": current_soc},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to %.1f%% (current SOC)", program_night_soc, current_soc)

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
                        "reason": f"PV surplus exceeds space ({pv_with_efficiency:.1f} > {battery_space:.1f})",
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
        program_night_soc = config.get(CONF_PROGRAM_NIGHT_SOC_ENTITY)
        min_soc = config.get("min_soc", 15)

        current_program_night_soc = None
        if program_night_soc:
            night_soc_state = hass.states.get(program_night_soc)
            if night_soc_state and night_soc_state.state not in ("unknown", "unavailable"):
                try:
                    current_program_night_soc = float(night_soc_state.state)
                except (ValueError, TypeError) as err:
                    _LOGGER.warning("Could not parse program night SOC: %s", err)

        if (
            current_program_night_soc is not None
            and current_program_night_soc > min_soc
            and not (pv_with_efficiency > battery_space)
        ):
            _LOGGER.info(
                "Restoring normal operation (current: %.0f%%, restoring to: %.0f%%)",
                current_program_night_soc,
                min_soc,
            )

            program_morning_soc = config.get(CONF_PROGRAM_MORNING_SOC_ENTITY)

            if program_morning_soc:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": program_morning_soc, "value": min_soc},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to %.0f%%", program_morning_soc, min_soc)

            if program_night_soc:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": program_night_soc, "value": min_soc},
                    blocking=True,
                )
                _LOGGER.debug("Set %s to %.0f%%", program_night_soc, min_soc)

            # Log to optimization sensors
            if "last_optimization_sensor" in hass.data[DOMAIN][entry.entry_id]:
                opt_sensor = hass.data[DOMAIN][entry.entry_id]["last_optimization_sensor"]
                opt_sensor.log_optimization(
                    "Normal Operation Restored",
                    {
                        "previous_soc": round(current_program_night_soc, 1),
                        "restored_to_soc": min_soc,
                        "pv_forecast_kwh": round(pv_forecast, 2),
                    },
                )
            if "optimization_history_sensor" in hass.data[DOMAIN][entry.entry_id]:
                hist_sensor = hass.data[DOMAIN][entry.entry_id]["optimization_history_sensor"]
                hist_sensor.add_entry(
                    "Normal Operation",
                    {
                        "previous": f"{current_program_night_soc:.0f}%",
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
        DOMAIN, SERVICE_OPTIMIZE_SCHEDULE, handle_optimize_schedule
    )

    _LOGGER.info("Energy Optimizer services registered")
