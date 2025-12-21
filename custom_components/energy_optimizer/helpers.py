"""Helper utilities for Energy Optimizer integration."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def get_active_program_entity(
    hass: HomeAssistant, config: dict[str, Any], current_time: datetime
) -> str | None:
    """Determine which program SOC entity should be updated based on time.
    
    Args:
        hass: Home Assistant instance to read entity states
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
        start_time_entity_id = config.get(start_key)
        
        if not soc_entity or not start_time_entity_id:
            continue
        
        # Get the state of the time entity
        time_state = hass.states.get(start_time_entity_id)
        if not time_state:
            _LOGGER.warning("Time entity %s not found for %s", start_time_entity_id, soc_key)
            continue
            
        try:
            # Extract time from entity state
            # time domain entities (Solarman): "HH:MM:SS"
            # input_datetime entities: "HH:MM:SS" or ISO datetime with T
            # sensor entities: "HH:MM" or "HH:MM:SS"
            time_value = time_state.state
            
            if not time_value or time_value in ("unknown", "unavailable"):
                _LOGGER.warning("Time entity %s has invalid state: %s", start_time_entity_id, time_value)
                continue
            
            _LOGGER.debug("Parsing time from %s: %s (domain: %s)", start_time_entity_id, time_value, time_state.domain)
            
            # Parse time string (handle HH:MM or HH:MM:SS format)
            # Also handle datetime strings by extracting just the time portion
            if "T" in time_value:
                # ISO datetime format, extract time portion robustly
                try:
                    dt = datetime.fromisoformat(time_value)
                    # Normalize to HH:MM:SS so downstream parsing is consistent
                    time_value = dt.time().strftime("%H:%M:%S")
                except ValueError:
                    # Fallback: manually strip timezone info from the time part
                    time_part = time_value.split("T", 1)[1]
                    for tz_sep in ("+", "-"):
                        if tz_sep in time_part:
                            time_part = time_part.split(tz_sep, 1)[0]
                            break
                    time_value = time_part
            
            # Strip any whitespace
            time_value = str(time_value).strip()
            
            time_parts = time_value.split(":")
            if len(time_parts) >= 2:
                start_dt = dt_time(int(time_parts[0]), int(time_parts[1]))
                _LOGGER.debug("Successfully parsed time for %s: %s -> %s", soc_key, time_value, start_dt)
            else:
                _LOGGER.warning("Invalid time format for %s: %s (expected HH:MM or HH:MM:SS)", start_time_entity_id, time_value)
                continue
                
            configured_programs.append((soc_entity, start_dt))
        except (ValueError, AttributeError, IndexError) as err:
            _LOGGER.error("Error parsing time from entity %s (state: %s): %s", start_time_entity_id, time_value, err)
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
