"""Helper utilities for Energy Optimizer integration."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging
import re
from typing import TYPE_CHECKING, Any, Literal

from homeassistant.util import dt as dt_util

from .utils.decision_dump import record_input


if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


def get_buy_plan(
    hass: HomeAssistant,
    *,
    entry_id: str,
    kind: Literal["night", "day"],
    for_date: date,
):
    """Return the persisted buy plan matching its semantic date.

    Consumers deliberately do not select a sensor by wall-clock phase.  The
    coordinator owns the plan lifecycle, so this helper is the single lookup
    seam for actions that need a concrete plan.
    """
    from .const import DOMAIN

    entry_data = hass.data.get(DOMAIN, {}).get(entry_id, {})
    manager = entry_data.get("buy_window_manager") if isinstance(entry_data, dict) else None
    return manager.get_plan(kind, for_date) if manager is not None else None


def _buy_window_manager(hass: HomeAssistant, entry_id: str) -> Any | None:
    """Return the lifecycle manager when coordinator-backed lookup is active."""
    from .const import DOMAIN

    entry_data = hass.data.get(DOMAIN, {}).get(entry_id, {})
    return entry_data.get("buy_window_manager") if isinstance(entry_data, dict) else None


def _buy_plan_for_relative_day(
    hass: HomeAssistant,
    *,
    entry_id: str,
    kind: Literal["night", "day"],
    offset: int = 0,
):
    """Resolve a persisted plan relative to the local calendar day."""
    from .const import DOMAIN

    if _buy_window_manager(hass, entry_id) is None:
        return None
    return get_buy_plan(
        hass,
        entry_id=entry_id,
        kind=kind,
        for_date=dt_util.as_local(dt_util.utcnow()).date() + timedelta(days=offset),
    )


def get_plan_for_today(hass: HomeAssistant, *, entry_id: str, kind: Literal["night", "day"]):
    """Return the persisted plan keyed by today's local date, if any."""
    return _buy_plan_for_relative_day(hass, entry_id=entry_id, kind=kind)


def day_buy_window_missing_for_today(hass: HomeAssistant, *, entry_id: str) -> bool:
    """Return True when the plan manager is active but today has no Day Buy Window.

    Without a plan Afternoon Charge has no window inside the low-tariff range,
    so callers skip it instead of charging at fallback hours.
    """
    if _buy_window_manager(hass, entry_id) is None:
        return False
    return get_plan_for_today(hass, entry_id=entry_id, kind="day") is None


def is_test_mode(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Return True when test mode is enabled for the config entry."""
    from .const import CONF_TEST_MODE, DOMAIN

    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if isinstance(entry_data, dict):
        test_mode_switch = entry_data.get("test_mode_switch")
        if test_mode_switch is not None:
            return bool(test_mode_switch.is_on)

    if CONF_TEST_MODE in entry.data:
        return bool(entry.data.get(CONF_TEST_MODE))
    return bool(entry.options.get(CONF_TEST_MODE, False))


def is_pv_forecast_compensation_enabled(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Return True when PV forecast compensation sensor usage is enabled."""
    from .const import CONF_USE_PV_FORECAST_COMPENSATION, DOMAIN

    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if isinstance(entry_data, dict):
        pv_comp_switch = entry_data.get("pv_forecast_compensation_switch")
        if pv_comp_switch is not None:
            return bool(pv_comp_switch.is_on)

    if CONF_USE_PV_FORECAST_COMPENSATION in entry.data:
        return bool(entry.data.get(CONF_USE_PV_FORECAST_COMPENSATION))
    return bool(entry.options.get(CONF_USE_PV_FORECAST_COMPENSATION, True))


def is_balancing_ongoing(hass: HomeAssistant, entry_id: str) -> bool:
    """Return True when balancing ongoing binary sensor is on."""
    from .const import DOMAIN

    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not isinstance(entry_data, dict):
        return False

    sensor = entry_data.get("balancing_ongoing_sensor")
    return bool(sensor and sensor.is_on)


def set_balancing_ongoing(
    hass: HomeAssistant, entry_id: str, *, ongoing: bool
) -> None:
    """Set balancing ongoing flag when sensor is available."""
    from .const import DOMAIN

    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not isinstance(entry_data, dict):
        return

    sensor = entry_data.get("balancing_ongoing_sensor")
    if sensor is not None:
        sensor.set_ongoing(ongoing)

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
        CONF_PROG1_SOC_ENTITY, CONF_PROG1_TIME_START_ENTITY,
        CONF_PROG2_SOC_ENTITY, CONF_PROG2_TIME_START_ENTITY,
        CONF_PROG3_SOC_ENTITY, CONF_PROG3_TIME_START_ENTITY,
        CONF_PROG4_SOC_ENTITY, CONF_PROG4_TIME_START_ENTITY,
        CONF_PROG5_SOC_ENTITY, CONF_PROG5_TIME_START_ENTITY,
        CONF_PROG6_SOC_ENTITY, CONF_PROG6_TIME_START_ENTITY,
    )
    
    programs = [
        (CONF_PROG1_SOC_ENTITY, CONF_PROG1_TIME_START_ENTITY),
        (CONF_PROG2_SOC_ENTITY, CONF_PROG2_TIME_START_ENTITY),
        (CONF_PROG3_SOC_ENTITY, CONF_PROG3_TIME_START_ENTITY),
        (CONF_PROG4_SOC_ENTITY, CONF_PROG4_TIME_START_ENTITY),
        (CONF_PROG5_SOC_ENTITY, CONF_PROG5_TIME_START_ENTITY),
        (CONF_PROG6_SOC_ENTITY, CONF_PROG6_TIME_START_ENTITY),
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

    # Special case: a single configured program is active all day.
    # Without this, next_start == start_dt and no time can match the empty window.
    if len(configured_programs) == 1:
        soc_entity, _start_dt = configured_programs[0]
        _LOGGER.debug("Only one program configured; treating %s as always active", soc_entity)
        return soc_entity
    
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


_UNAVAILABLE_STATE_VALUES = (None, "unknown", "unavailable")

StateReadError = Literal["missing", "unavailable", "invalid"]


def get_float_state_info(
    hass: HomeAssistant,
    entity_id: str | None,
) -> tuple[float | None, str | None, StateReadError | None]:
    """Read a float from an entity state.

    Returns a tuple of:
    - value: parsed float or None
    - raw: raw state string (when available)
    - error: one of "missing", "unavailable", "invalid" or None when ok
    """
    if not entity_id:
        record_input(
            "float_state:unconfigured",
            source=None,
            value=None,
            status="missing",
        )
        return None, None, "missing"

    state = hass.states.get(entity_id)
    if not state:
        record_input(
            f"float_state:{entity_id}",
            source=entity_id,
            value=None,
            status="missing",
        )
        return None, None, "missing"

    raw = state.state
    if raw in _UNAVAILABLE_STATE_VALUES:
        raw_str = None if raw is None else str(raw)
        record_input(
            f"float_state:{entity_id}",
            source=entity_id,
            value=raw,
            status="unavailable",
        )
        return None, raw_str, "unavailable"

    try:
        value = float(raw)
        record_input(f"float_state:{entity_id}", source=entity_id, value=raw)
        return value, str(raw), None
    except (ValueError, TypeError):
        record_input(
            f"float_state:{entity_id}",
            source=entity_id,
            value=raw,
            status="invalid",
        )
        return None, str(raw), "invalid"


def get_required_float_state(
    hass: HomeAssistant,
    entity_id: str | None,
    *,
    entity_name: str,
) -> float | None:
    """Fetch a required float state with logging and validation."""
    if not entity_id:
        _LOGGER.error("%s not configured", entity_name)
        return None

    value, raw, error = get_float_state_info(hass, entity_id)
    if error is not None or value is None:
        if error in ("missing", "unavailable"):
            _LOGGER.warning("%s %s unavailable", entity_name, entity_id)
        else:
            _LOGGER.warning("%s %s has invalid value: %s", entity_name, entity_id, raw)
        return None

    return value


def get_required_float_state_or_attribute(
    hass: HomeAssistant,
    entity_id: str | None,
    *,
    entity_name: str,
    attribute_name: str,
) -> float | None:
    """Fetch a float value from an attribute, falling back to the entity state.

    This supports built-in pricing window sensors whose user-facing state is a time
    while the business price lives in a dedicated attribute.
    """
    if not entity_id:
        _LOGGER.error("%s not configured", entity_name)
        return None

    state = hass.states.get(str(entity_id))
    if state is None:
        _LOGGER.warning("%s %s unavailable", entity_name, entity_id)
        return None

    raw_attribute = state.attributes.get(attribute_name)
    if raw_attribute not in _UNAVAILABLE_STATE_VALUES:
        try:
            return float(raw_attribute)
        except (TypeError, ValueError):
            _LOGGER.warning(
                "%s %s has invalid attribute %s: %s",
                entity_name,
                entity_id,
                attribute_name,
                raw_attribute,
            )
            return None

    value, raw_state, error = get_float_state_info(hass, str(entity_id))
    if error is None and value is not None:
        return value

    if raw_attribute in _UNAVAILABLE_STATE_VALUES and attribute_name in state.attributes:
        _LOGGER.warning(
            "%s %s has unavailable attribute %s",
            entity_name,
            entity_id,
            attribute_name,
        )
        return None

    if error in ("missing", "unavailable"):
        _LOGGER.warning("%s %s unavailable", entity_name, entity_id)
    else:
        _LOGGER.warning("%s %s has invalid value: %s", entity_name, entity_id, raw_state)
    return None


def get_buy_price_payload(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    entry_id: str,
) -> list[dict[str, object]] | None:
    """Return the coordinator's immutable snapshot of future buy-price points."""
    from .const import CONF_BUY_PRICE_SENSOR, DOMAIN

    buy_price_entity = config.get(CONF_BUY_PRICE_SENSOR)
    if not buy_price_entity:
        return None

    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not isinstance(entry_data, dict):
        return None
    coordinator = entry_data.get("coordinator")
    coordinator_data = getattr(coordinator, "data", None)
    if not isinstance(coordinator_data, dict):
        return None
    payloads = coordinator_data.get("price_payloads")
    if not isinstance(payloads, dict):
        return None
    payload = payloads.get(str(buy_price_entity))
    if not isinstance(payload, dict):
        return None

    combined = payload.get("prices")
    if isinstance(combined, list):
        prices = [value for value in combined if isinstance(value, dict)]
        return prices or None

    prices = []
    seen_times: set[str] = set()
    for key in ("prices_today", "prices_tomorrow"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            raw_time = value.get("time")
            time_key = str(raw_time)
            if time_key in seen_times:
                continue
            seen_times.add(time_key)
            prices.append(value)
    return prices or None


def get_float_value(
    hass: HomeAssistant,
    entity_id: str | None,
    *,
    default: float,
) -> float:
    """Read a float from an entity state, falling back to a default."""
    value, _raw, error = get_float_state_info(hass, entity_id)
    if error is not None or value is None:
        return default
    return value


def _parse_hour_from_state_value(state_value: object) -> int | None:
    """Parse hour from datetime, time, or numeric state value."""
    raw_value = str(state_value)
    dt_value = dt_util.parse_datetime(raw_value)
    if dt_value is not None:
        return dt_util.as_local(dt_value).hour

    time_value = dt_util.parse_time(raw_value)
    if time_value is not None:
        return time_value.hour

    try:
        return int(float(raw_value))
    except (TypeError, ValueError):
        return None


def _parse_time_from_state_value(state_value: object) -> time | None:
    """Parse time from datetime, time, or first segment of a range state value."""
    raw_value = str(state_value)
    if re.match(r"^\s*\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\s*$", raw_value):
        raw_value = raw_value.split("-", 1)[0].strip()

    dt_value = dt_util.parse_datetime(raw_value)
    if dt_value is not None:
        local_dt = dt_util.as_local(dt_value)
        return time(local_dt.hour, local_dt.minute)

    parsed_time = dt_util.parse_time(raw_value)
    if parsed_time is not None:
        return time(parsed_time.hour, parsed_time.minute)

    try:
        native_dt = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        return time(native_dt.hour, native_dt.minute)
    except ValueError:
        return None


def _resolve_time_from_state_or_attribute(
    hass: HomeAssistant,
    entity_id: str | None,
    *,
    attribute_name: str | None = None,
) -> time | None:
    """Resolve time from an entity attribute or, if absent, from its state."""
    if not entity_id:
        return None

    state = hass.states.get(str(entity_id))
    if state is None:
        return None

    attributes = getattr(state, "attributes", {})
    if not isinstance(attributes, dict):
        attributes = {}

    if attribute_name:
        raw_attribute = attributes.get(attribute_name)
        if raw_attribute not in _UNAVAILABLE_STATE_VALUES:
            return _parse_time_from_state_value(raw_attribute)

    return _parse_time_from_state_value(state.state)


def resolve_prog4_start_time(
    hass: HomeAssistant,
    config: dict[str, object],
) -> time | None:
    """Resolve the configured Program 4 start time without a fallback."""
    from .const import CONF_PROG4_TIME_START_ENTITY

    entity_id = config.get(CONF_PROG4_TIME_START_ENTITY)
    resolved_time = _resolve_time_from_state_or_attribute(
        hass,
        str(entity_id) if entity_id else None,
    )
    if resolved_time is None:
        _LOGGER.warning("Program 4 start time is unavailable or invalid")
    return resolved_time


def resolve_tariff_end_hour(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    default_hour: int = 13,
) -> int:
    """Resolve high tariff end hour from configured sensor with fallback."""
    from .const import CONF_HIGH_TARIFF_END_HOUR_SENSOR

    tariff_end_hour = default_hour
    tariff_end_entity = config.get(CONF_HIGH_TARIFF_END_HOUR_SENSOR)
    if tariff_end_entity:
        tariff_end_state = hass.states.get(str(tariff_end_entity))
        if tariff_end_state is None:
            _LOGGER.warning(
                "Tariff end hour entity %s unavailable, using default %s",
                tariff_end_entity,
                default_hour,
            )
        else:
            state_value = tariff_end_state.state
            parsed_hour = _parse_hour_from_state_value(state_value)
            if parsed_hour is not None:
                tariff_end_hour = parsed_hour
            else:
                _LOGGER.warning(
                    "Tariff end hour entity %s has invalid value %s, using default %s",
                    tariff_end_entity,
                    state_value,
                    default_hour,
                )
    else:
        _LOGGER.warning(
            "High tariff end hour sensor not configured, using default %s",
            default_hour,
        )

    if tariff_end_hour < 7 or tariff_end_hour > 24:
        _LOGGER.warning(
            "Tariff end hour %s out of range, using default %s",
            tariff_end_hour,
            default_hour,
        )
        tariff_end_hour = default_hour

    return tariff_end_hour


def resolve_tariff_start_hour(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    default_hour: int = 15,
) -> int:
    """Resolve high tariff start hour from configured sensor with fallback."""
    from .const import CONF_HIGH_TARIFF_START_HOUR_SENSOR

    tariff_start_hour = default_hour
    tariff_start_entity = config.get(CONF_HIGH_TARIFF_START_HOUR_SENSOR)
    if tariff_start_entity:
        tariff_start_state = hass.states.get(str(tariff_start_entity))
        if tariff_start_state is None:
            _LOGGER.warning(
                "Tariff start hour entity %s unavailable, using default %s",
                tariff_start_entity,
                default_hour,
            )
        else:
            state_value = tariff_start_state.state
            parsed_hour = _parse_hour_from_state_value(state_value)
            if parsed_hour is not None:
                tariff_start_hour = parsed_hour
            else:
                _LOGGER.warning(
                    "Tariff start hour entity %s has invalid value %s, using default %s",
                    tariff_start_entity,
                    state_value,
                    default_hour,
                )
    else:
        _LOGGER.warning(
            "High tariff start hour sensor not configured, using default %s",
            default_hour,
        )

    if tariff_start_hour < 0 or tariff_start_hour > 23:
        _LOGGER.warning(
            "Tariff start hour %s out of range, using default %s",
            tariff_start_hour,
            default_hour,
        )
        tariff_start_hour = default_hour

    return tariff_start_hour
