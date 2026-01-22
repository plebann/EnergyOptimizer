"""Service handlers for Energy Optimizer integration."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.core import ServiceCall
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SERVICE_MORNING_GRID_CHARGE, SERVICE_OVERNIGHT_SCHEDULE
from .helpers import get_float_state_info
from .service_handlers.morning import async_handle_morning_grid_charge
from .service_handlers.overnight import async_handle_overnight_schedule

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


SERVICE_FIELD_ENTRY_ID = "entry_id"

SERVICE_SCHEMA_OVERNIGHT_SCHEDULE = vol.Schema(
    {
        vol.Optional(SERVICE_FIELD_ENTRY_ID): vol.Coerce(str),
    }
)

SERVICE_SCHEMA_MORNING_GRID_CHARGE = vol.Schema(
    {
        vol.Optional(SERVICE_FIELD_ENTRY_ID): vol.Coerce(str),
        vol.Optional("margin", default=1.1): vol.All(
            vol.Coerce(float), vol.Range(min=1.0, max=1.5)
        ),
    }
)


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

    current_soc, _raw, error = get_float_state_info(hass, soc_sensor)
    if error is not None or current_soc is None:
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
    async def _handle_morning_grid_charge(call: ServiceCall) -> None:
        await async_handle_morning_grid_charge(hass, call)

    async def _handle_overnight_schedule(call: ServiceCall) -> None:
        await async_handle_overnight_schedule(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_MORNING_GRID_CHARGE,
        _handle_morning_grid_charge,
        schema=SERVICE_SCHEMA_MORNING_GRID_CHARGE,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_OVERNIGHT_SCHEDULE,
        _handle_overnight_schedule,
        schema=SERVICE_SCHEMA_OVERNIGHT_SCHEDULE,
    )

    _LOGGER.info("Energy Optimizer services registered")
