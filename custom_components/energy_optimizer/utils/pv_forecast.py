"""PV forecast utilities."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import TYPE_CHECKING

from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_PV_EFFICIENCY,
    CONF_PV_FORECAST_REMAINING,
    CONF_PV_FORECAST_TODAY,
    CONF_PV_FORECAST_TOMORROW,
    CONF_PV_PRODUCTION_SENSOR,
    DEFAULT_PV_EFFICIENCY,
    DOMAIN,
)
from ..helpers import is_pv_forecast_compensation_enabled
from .decision_dump import record_input
from .time_window import build_hour_window

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MorningPVForecast:
    """Validated PV forecast data for a morning decision horizon."""

    total_kwh: float
    hourly_kwh: dict[int, float]
    status: str
    method: str
    source_entity: str | None
    aggregate_kwh: float | None
    raw_hourly_kwh: float | None
    difference_kwh: float | None
    tolerance_kwh: float | None
    daylight_hours: list[int]
    sufficiency_available: bool
    source_state: str | None = None
    source_last_updated: str | None = None
    source_last_changed: str | None = None
    evaluation_time: str | None = None
    evaluation_time_utc: str | None = None
    evaluation_timezone: str | None = None
    selected_attribute: str | None = None
    hourly_payload_present: bool = False
    hourly_payload_type: str | None = None
    hourly_payload_length: int | None = None
    first_period_start: str | None = None
    last_period_start: str | None = None
    first_period_local_date: str | None = None
    last_period_local_date: str | None = None
    failure_reason: str | None = None

    def audit_details(self) -> dict[str, object]:
        """Return PV provenance suitable for decision audit details."""
        return {
            "source_entity": self.source_entity,
            "source_state": self.source_state,
            "source_last_updated": self.source_last_updated,
            "source_last_changed": self.source_last_changed,
            "evaluation_time": self.evaluation_time,
            "evaluation_time_utc": self.evaluation_time_utc,
            "evaluation_timezone": self.evaluation_timezone,
            "selected_attribute": self.selected_attribute,
            "hourly_payload_present": self.hourly_payload_present,
            "hourly_payload_type": self.hourly_payload_type,
            "hourly_payload_length": self.hourly_payload_length,
            "first_period_start": self.first_period_start,
            "last_period_start": self.last_period_start,
            "first_period_local_date": self.first_period_local_date,
            "last_period_local_date": self.last_period_local_date,
            "aggregate_kwh": _round_or_none(self.aggregate_kwh),
            "raw_hourly_kwh": _round_or_none(self.raw_hourly_kwh),
            "difference_kwh": _round_or_none(self.difference_kwh),
            "tolerance_kwh": _round_or_none(self.tolerance_kwh),
            "final_status": self.status,
            "final_method": self.method,
            "failure_reason": self.failure_reason,
            "pv_data_status": self.status,
            "pv_forecast_method": self.method,
            "pv_source_entity": self.source_entity,
            "pv_aggregate_kwh": _round_or_none(self.aggregate_kwh),
            "pv_hourly_raw_kwh": _round_or_none(self.raw_hourly_kwh),
            "pv_hourly_difference_kwh": _round_or_none(self.difference_kwh),
            "pv_hourly_tolerance_kwh": _round_or_none(self.tolerance_kwh),
            "pv_daylight_hours": self.daylight_hours,
            "pv_sufficiency_status": (
                "available" if self.sufficiency_available else "unavailable"
            ),
        }


@dataclass(frozen=True, slots=True)
class _HourlyForecastParseResult:
    """Hourly payload and its validation metadata."""

    hourly_kwh: dict[int, float]
    status: str
    failure_reason: str | None
    selected_attribute: str | None
    hourly_payload_present: bool
    hourly_payload_type: str | None
    hourly_payload_length: int | None
    first_period_start: str | None
    last_period_start: str | None
    first_period_local_date: str | None
    last_period_local_date: str | None


def get_morning_pv_forecast(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    start_hour: int,
    end_hour: int,
    apply_efficiency: bool = True,
) -> MorningPVForecast:
    """Return validated hourly PV or a documented morning fallback."""
    source_entity = config.get(CONF_PV_FORECAST_TODAY)
    if not source_entity:
        now = dt_util.as_local(dt_util.now())
        return _invalid_morning_forecast(
            source_entity=None,
            failure_reason="entity_missing",
            **_evaluation_details(now),
        )

    pv_state = hass.states.get(source_entity)
    now = dt_util.as_local(dt_util.now())
    snapshot_details = _snapshot_details(pv_state, now)
    if pv_state is None:
        _LOGGER.warning("Morning PV forecast sensor %s unavailable", source_entity)
        return _invalid_morning_forecast(
            source_entity=str(source_entity),
            failure_reason="entity_missing",
            **snapshot_details,
        )

    hourly_result = _collect_today_hourly_kwh(pv_state, now)
    hourly_details = _hourly_audit_details(hourly_result)
    try:
        aggregate_kwh = float(pv_state.state)
    except (ValueError, TypeError):
        _LOGGER.warning(
            "Morning PV forecast sensor %s has invalid aggregate value: %s",
            source_entity,
            pv_state.state,
        )
        return _invalid_morning_forecast(
            source_entity=str(source_entity),
            failure_reason="aggregate_invalid",
            **snapshot_details,
            **hourly_details,
        )
    if aggregate_kwh < 0:
        _LOGGER.warning(
            "Morning PV forecast sensor %s has negative aggregate value: %s",
            source_entity,
            aggregate_kwh,
        )
        return _invalid_morning_forecast(
            source_entity=str(source_entity),
            failure_reason="aggregate_invalid",
            **snapshot_details,
            **hourly_details,
        )

    raw_hourly = hourly_result.hourly_kwh
    hourly_status = hourly_result.status
    if hourly_status == "valid_hourly":
        raw_hourly_total = sum(raw_hourly.values())
        tolerance_kwh = max(0.25, aggregate_kwh * 0.1)
        difference_kwh = abs(raw_hourly_total - aggregate_kwh)
        last_updated = getattr(pv_state, "last_updated", None)
        if isinstance(last_updated, datetime) and dt_util.as_local(last_updated).date() < now.date():
            hourly_status = "stale_hourly"
            failure_reason = "stale_sensor_update"
        elif difference_kwh > tolerance_kwh:
            hourly_status = "invalid_hourly"
            failure_reason = "hourly_aggregate_mismatch"
        else:
            failure_reason = None
    else:
        raw_hourly_total = None
        tolerance_kwh = None
        difference_kwh = None
        failure_reason = hourly_result.failure_reason

    hour_window = build_hour_window(start_hour, end_hour)
    if hourly_status == "valid_hourly":
        hourly_kwh = {hour: raw_hourly.get(hour, 0.0) for hour in hour_window}
        if apply_efficiency:
            hourly_kwh = _apply_pv_efficiency(config, hourly_kwh)
        return MorningPVForecast(
            total_kwh=sum(hourly_kwh.values()),
            hourly_kwh=hourly_kwh,
            status=hourly_status,
            method=(
                "detailed_hourly"
                if hourly_result.selected_attribute == "detailedHourly"
                else "detailed_forecast_fallback"
            ),
            source_entity=str(source_entity),
            aggregate_kwh=aggregate_kwh,
            raw_hourly_kwh=raw_hourly_total,
            difference_kwh=difference_kwh,
            tolerance_kwh=tolerance_kwh,
            daylight_hours=[],
            sufficiency_available=True,
            failure_reason=None,
            **snapshot_details,
            **hourly_details,
        )

    daylight_hours = _get_daylight_hours(hass, now)
    if daylight_hours:
        fallback_method = "daylight_uniform"
        hourly_value = aggregate_kwh / len(daylight_hours)
        hourly_kwh = {
            hour: hourly_value if hour in daylight_hours else 0.0
            for hour in hour_window
        }
    else:
        fallback_method = "half_aggregate"
        hourly_kwh = {hour: 0.0 for hour in hour_window}
        if hourly_kwh:
            hourly_kwh[next(iter(hourly_kwh))] = aggregate_kwh * 0.5

    if apply_efficiency:
        hourly_kwh = _apply_pv_efficiency(config, hourly_kwh)
    return MorningPVForecast(
        total_kwh=sum(hourly_kwh.values()),
        hourly_kwh=hourly_kwh,
        status=hourly_status,
        method=fallback_method,
        source_entity=str(source_entity),
        aggregate_kwh=aggregate_kwh,
        raw_hourly_kwh=raw_hourly_total,
        difference_kwh=difference_kwh,
        tolerance_kwh=tolerance_kwh,
        daylight_hours=daylight_hours,
        sufficiency_available=False,
        failure_reason=failure_reason,
        **snapshot_details,
        **hourly_details,
    )


def _invalid_morning_forecast(
    source_entity: str | None,
    *,
    failure_reason: str,
    **details: object,
) -> MorningPVForecast:
    """Return the safe fallback when the aggregate forecast is invalid."""
    return MorningPVForecast(
        total_kwh=0.0,
        hourly_kwh={},
        status="invalid_forecast",
        method="none",
        source_entity=source_entity,
        aggregate_kwh=None,
        raw_hourly_kwh=None,
        difference_kwh=None,
        tolerance_kwh=None,
        daylight_hours=[],
        sufficiency_available=False,
        failure_reason=failure_reason,
        **details,
    )


def _collect_today_hourly_kwh(
    pv_state: object, now: datetime
) -> _HourlyForecastParseResult:
    """Return raw hourly PV for today or a data-quality status."""
    attributes = getattr(pv_state, "attributes", {})
    selected_attribute = "detailedHourly"
    detailed = attributes.get(selected_attribute)
    if not isinstance(detailed, list) and "detailedForecast" in attributes:
        selected_attribute = "detailedForecast"
        detailed = attributes.get(selected_attribute)

    payload_present = selected_attribute in attributes
    payload_type = type(detailed).__name__ if payload_present else None
    payload_length = len(detailed) if isinstance(detailed, list) else None
    if not payload_present:
        return _hourly_parse_failure(
            "missing_hourly",
            "hourly_attribute_missing",
            selected_attribute=None,
        )
    if not isinstance(detailed, list):
        return _hourly_parse_failure(
            "invalid_hourly",
            "hourly_not_list",
            selected_attribute=selected_attribute,
            hourly_payload_present=True,
            hourly_payload_type=payload_type,
        )
    if not detailed:
        return _hourly_parse_failure(
            "missing_hourly",
            "hourly_empty",
            selected_attribute=selected_attribute,
            hourly_payload_present=True,
            hourly_payload_type=payload_type,
            hourly_payload_length=0,
        )

    hourly: dict[int, float] = {}
    periods: list[tuple[datetime, str]] = []
    for item in detailed:
        if not isinstance(item, dict):
            return _hourly_parse_failure(
                "invalid_hourly",
                "record_not_mapping",
                selected_attribute=selected_attribute,
                hourly_payload_present=True,
                hourly_payload_type=payload_type,
                hourly_payload_length=payload_length,
                periods=periods,
                now=now,
            )
        period_start = item.get("period_start")
        estimate = item.get("pv_estimate")
        if period_start is None:
            return _hourly_parse_failure(
                "invalid_hourly",
                "period_start_missing",
                selected_attribute=selected_attribute,
                hourly_payload_present=True,
                hourly_payload_type=payload_type,
                hourly_payload_length=payload_length,
                periods=periods,
                now=now,
            )
        parsed = dt_util.parse_datetime(str(period_start))
        if parsed is None:
            return _hourly_parse_failure(
                "invalid_hourly",
                "period_start_invalid",
                selected_attribute=selected_attribute,
                hourly_payload_present=True,
                hourly_payload_type=payload_type,
                hourly_payload_length=payload_length,
                periods=periods,
                now=now,
            )
        periods.append((parsed, str(period_start)))
        if estimate is None:
            return _hourly_parse_failure(
                "invalid_hourly",
                "pv_estimate_missing",
                selected_attribute=selected_attribute,
                hourly_payload_present=True,
                hourly_payload_type=payload_type,
                hourly_payload_length=payload_length,
                periods=periods,
                now=now,
            )
        try:
            value = float(estimate)
        except (ValueError, TypeError):
            return _hourly_parse_failure(
                "invalid_hourly",
                "pv_estimate_invalid",
                selected_attribute=selected_attribute,
                hourly_payload_present=True,
                hourly_payload_type=payload_type,
                hourly_payload_length=payload_length,
                periods=periods,
                now=now,
            )
        local_period = dt_util.as_local(parsed)
        if local_period.date() != now.date():
            return _hourly_parse_failure(
                "invalid_hourly",
                "record_local_date_mismatch",
                selected_attribute=selected_attribute,
                hourly_payload_present=True,
                hourly_payload_type=payload_type,
                hourly_payload_length=payload_length,
                periods=periods,
                now=now,
            )
        hourly[local_period.hour] = hourly.get(local_period.hour, 0.0) + value
    return _HourlyForecastParseResult(
        hourly_kwh=hourly,
        status="valid_hourly",
        failure_reason=None,
        selected_attribute=selected_attribute,
        hourly_payload_present=True,
        hourly_payload_type=payload_type,
        hourly_payload_length=payload_length,
        **_period_audit_details(periods, now),
    )


def _hourly_parse_failure(
    status: str,
    failure_reason: str,
    *,
    selected_attribute: str | None,
    hourly_payload_present: bool = False,
    hourly_payload_type: str | None = None,
    hourly_payload_length: int | None = None,
    periods: list[tuple[datetime, str]] | None = None,
    now: datetime | None = None,
) -> _HourlyForecastParseResult:
    """Build invalid hourly metadata without retaining payload records."""
    period_details = _period_audit_details(periods or [], now) if now is not None else {
        "first_period_start": None,
        "last_period_start": None,
        "first_period_local_date": None,
        "last_period_local_date": None,
    }
    return _HourlyForecastParseResult(
        hourly_kwh={},
        status=status,
        failure_reason=failure_reason,
        selected_attribute=selected_attribute,
        hourly_payload_present=hourly_payload_present,
        hourly_payload_type=hourly_payload_type,
        hourly_payload_length=hourly_payload_length,
        **period_details,
    )


def _period_audit_details(
    periods: list[tuple[datetime, str]],
    now: datetime,
) -> dict[str, str | None]:
    """Return first and last source periods without storing hourly payloads."""
    if not periods:
        return {
            "first_period_start": None,
            "last_period_start": None,
            "first_period_local_date": None,
            "last_period_local_date": None,
        }
    first_period, first_source = min(periods, key=lambda period: period[0])
    last_period, last_source = max(periods, key=lambda period: period[0])
    return {
        "first_period_start": first_source,
        "last_period_start": last_source,
        "first_period_local_date": dt_util.as_local(first_period).date().isoformat(),
        "last_period_local_date": dt_util.as_local(last_period).date().isoformat(),
    }


def _snapshot_details(pv_state: object | None, now: datetime) -> dict[str, object]:
    """Return a scalar-only snapshot of the forecast entity read."""
    details = _evaluation_details(now)
    if pv_state is None:
        return details
    source_state = getattr(pv_state, "state", None)
    details.update(
        {
            "source_state": str(source_state) if source_state is not None else None,
            "source_last_updated": _serialize_datetime(
                getattr(pv_state, "last_updated", None)
            ),
            "source_last_changed": _serialize_datetime(
                getattr(pv_state, "last_changed", None)
            ),
        }
    )
    return details


def _evaluation_details(now: datetime) -> dict[str, str]:
    """Serialize the optimizer's actual local evaluation instant."""
    timezone = getattr(now.tzinfo, "key", None) or str(now.tzinfo)
    return {
        "evaluation_time": now.isoformat(),
        "evaluation_time_utc": dt_util.as_utc(now).isoformat(),
        "evaluation_timezone": timezone,
    }


def _serialize_datetime(value: object) -> str | None:
    """Serialize an entity timestamp only when Home Assistant supplied one."""
    return dt_util.as_local(value).isoformat() if isinstance(value, datetime) else None


def _hourly_audit_details(
    result: _HourlyForecastParseResult,
) -> dict[str, object]:
    """Map parser metadata to the public forecast audit model."""
    return {
        "selected_attribute": result.selected_attribute,
        "hourly_payload_present": result.hourly_payload_present,
        "hourly_payload_type": result.hourly_payload_type,
        "hourly_payload_length": result.hourly_payload_length,
        "first_period_start": result.first_period_start,
        "last_period_start": result.last_period_start,
        "first_period_local_date": result.first_period_local_date,
        "last_period_local_date": result.last_period_local_date,
    }


def _get_daylight_hours(hass: HomeAssistant, now: datetime) -> list[int]:
    """Return full local daylight hours when both sun boundaries are available."""
    sun_state = hass.states.get("sun.sun")
    if sun_state is None:
        return []
    next_rising = dt_util.parse_datetime(str(sun_state.attributes.get("next_rising")))
    next_setting = dt_util.parse_datetime(str(sun_state.attributes.get("next_setting")))
    if next_rising is None or next_setting is None:
        return []

    local_rising = dt_util.as_local(next_rising)
    local_setting = dt_util.as_local(next_setting)
    if local_rising.date() != now.date():
        current_rising = get_astral_event_date(hass, "sunrise", now.date())
        if current_rising is None:
            return []
        local_rising = dt_util.as_local(current_rising)
    if local_rising.date() != now.date() or local_setting.date() != now.date():
        return []
    if local_setting.hour <= local_rising.hour:
        return []
    return list(range(local_rising.hour + (local_rising.minute > 0), local_setting.hour))


def _round_or_none(value: float | None) -> float | None:
    """Round an optional audit value."""
    return round(value, 3) if value is not None else None


def get_forecast_adjusted_kwh(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    pv_forecast_today_entity: str | None = None,
    pv_forecast_remaining_entity: str | None = None,
    pv_production_entity: str | None = None,
    entry_id: str | None = None,
) -> tuple[float | None, str | None]:
    """Return adjusted PV forecast for today based on production progress."""
    today_kwh, remaining_kwh, production_kwh, reason = _get_forecast_inputs(
        hass,
        config,
        pv_forecast_today_entity=pv_forecast_today_entity,
        pv_forecast_remaining_entity=pv_forecast_remaining_entity,
        pv_production_entity=pv_production_entity,
    )
    if reason is not None:
        return None, reason

    forecast_adjusted, factor_today, reason = _calculate_forecast_adjustment(
        today_kwh,
        remaining_kwh,
        production_kwh,
    )
    if reason is not None or factor_today is None:
        return None, reason

    factor_sensor = _get_sensor_compensation_factor(hass, entry_id)
    factor_combined = _combine_compensation_factors(factor_today, factor_sensor)
    if factor_combined is None:
        return None, "missing_compensation"

    forecast_adjusted = today_kwh * factor_combined
    return forecast_adjusted, None


def get_pv_forecast(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    start_hour: int,
    end_hour: int,
    apply_efficiency: bool = True,
    compensate: bool = False,
    entry_id: str | None = None,
) -> dict[int, float]:
    """Return PV forecast energy per hour between start and end hour."""
    hourly_kwh = _collect_pv_forecast_hourly_kwh(
        hass, config, start_hour=start_hour, end_hour=end_hour
    )

    if compensate:
        hourly_kwh = _apply_pv_compensation(
            hass,
            config,
            hourly_kwh,
            start_hour=start_hour,
            end_hour=end_hour,
            entry_id=entry_id,
        )

    if apply_efficiency:
        hourly_kwh = _apply_pv_efficiency(config, hourly_kwh)

    return sum(hourly_kwh.values()), hourly_kwh


def get_pv_compensation_factor(
    hass: HomeAssistant, entry_id: str | None
) -> float | None:
    """Return the PV compensation factor from the integration sensor."""
    return _get_sensor_compensation_factor(hass, entry_id)


def _collect_pv_forecast_hourly_kwh(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    start_hour: int,
    end_hour: int,
) -> dict[int, float]:
    """Collect PV forecast energy per hour without efficiency adjustments."""
    hour_window = build_hour_window(start_hour, end_hour)
    hourly_kwh: dict[int, float] = {hour: 0.0 for hour in hour_window}
    if not hour_window:
        return hourly_kwh

    now_hour = dt_util.now().hour
    today_sensor = config.get(CONF_PV_FORECAST_TODAY)
    tomorrow_sensor = config.get(CONF_PV_FORECAST_TOMORROW)
    segments: list[tuple[list[dict], int, int]] = []

    if end_hour < start_hour:
        detailed_today = _get_detailed_forecast(hass, today_sensor, "today")
        if detailed_today:
            segments.append((detailed_today, start_hour, 24))
        detailed_tomorrow = _get_detailed_forecast(hass, tomorrow_sensor, "tomorrow")
        if detailed_tomorrow:
            segments.append((detailed_tomorrow, 0, end_hour))
    elif start_hour < now_hour:
        detailed = _get_detailed_forecast(hass, tomorrow_sensor, "tomorrow")
        if detailed:
            segments.append((detailed, start_hour, end_hour))
    elif end_hour > start_hour:
        detailed = _get_detailed_forecast(hass, today_sensor, "today")
        if detailed:
            segments.append((detailed, start_hour, end_hour))

    if not segments:
        return hourly_kwh

    for detailed, window_start, window_end in segments:
        for item in detailed:
            if not isinstance(item, dict):
                continue
            period_start = item.get("period_start")
            pv_estimate = item.get("pv_estimate")
            if period_start is None or pv_estimate is None:
                continue
            dt_value = dt_util.parse_datetime(str(period_start))
            if dt_value is None:
                continue
            if window_start <= dt_value.hour < window_end:
                try:
                    if dt_value.hour in hourly_kwh:
                        hourly_kwh[dt_value.hour] += float(pv_estimate)
                except (ValueError, TypeError):
                    continue

    return hourly_kwh


def _get_detailed_forecast(
    hass: HomeAssistant, sensor: str | None, label: str
) -> list[dict] | None:
    if not sensor:
        _LOGGER.warning("PV forecast %s sensor not configured", label)
        return None
    pv_state = hass.states.get(sensor)
    record_input(
        f"pv_forecast_{label}",
        source=sensor,
        value=None if pv_state is None else pv_state.state,
        status=(
            "missing"
            if pv_state is None
            else "unavailable"
            if pv_state.state in {"unknown", "unavailable"}
            else "ok"
        ),
        attributes=(
            {
                key: pv_state.attributes[key]
                for key in ("detailedHourly", "detailedForecast")
                if key in pv_state.attributes
            }
            if pv_state is not None
            else None
        ),
    )
    if pv_state is None:
        _LOGGER.warning("PV forecast %s sensor %s unavailable", label, sensor)
        return None
    detailed = pv_state.attributes.get("detailedHourly")
    if not isinstance(detailed, list):
        detailed = pv_state.attributes.get("detailedForecast")
    if not isinstance(detailed, list):
        _LOGGER.warning(
            "PV forecast %s sensor has no detailedHourly/detailedForecast: %s",
            label,
            sensor,
        )
        return None
    return detailed


def _apply_pv_efficiency(
    config: dict[str, object], hourly_kwh: dict[int, float]
) -> dict[int, float]:
    pv_efficiency = config.get(CONF_PV_EFFICIENCY, DEFAULT_PV_EFFICIENCY)
    if pv_efficiency is None:
        return hourly_kwh

    try:
        efficiency = float(pv_efficiency)
    except (ValueError, TypeError):
        efficiency = DEFAULT_PV_EFFICIENCY

    return {hour: value * efficiency for hour, value in hourly_kwh.items()}


def _apply_pv_compensation(
    hass: HomeAssistant,
    config: dict[str, object],
    hourly_kwh: dict[int, float],
    *,
    start_hour: int,
    end_hour: int,
    entry_id: str | None = None,
) -> dict[int, float]:
    today_kwh, remaining_kwh, production_kwh, reason = _get_forecast_inputs(
        hass, config
    )
    if reason is not None:
        return hourly_kwh

    _, factor_today, reason = _calculate_forecast_adjustment(
        today_kwh,
        remaining_kwh,
        production_kwh,
    )
    if reason is not None or factor_today is None:
        return hourly_kwh

    factor_sensor = _get_sensor_compensation_factor(hass, entry_id)
    factor_combined = _combine_compensation_factors(factor_today, factor_sensor)
    if factor_combined is None:
        return hourly_kwh

    factor_combined = min(factor_combined, 1.2)
    return {hour: value * factor_combined for hour, value in hourly_kwh.items()}


def _combine_compensation_factors(
    factor_today: float | None, factor_sensor: float | None
) -> float | None:
    if factor_today is None and factor_sensor is None:
        return None
    if factor_today is None:
        return factor_sensor
    if factor_sensor is None:
        return factor_today
    return (factor_today + factor_sensor) / 2.0


def _get_sensor_compensation_factor(
    hass: HomeAssistant, entry_id: str | None
) -> float | None:
    if entry_id is None:
        return None
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        return None
    if not is_pv_forecast_compensation_enabled(hass, entry):
        return None
    if DOMAIN not in hass.data or entry_id not in hass.data[DOMAIN]:
        return None
    sensor = hass.data[DOMAIN][entry_id].get("pv_forecast_compensation_sensor")
    if sensor is None:
        return None
    value = getattr(sensor, "native_value", None)
    record_input(
        "pv_forecast_compensation_factor",
        source=None,
        value=value,
        status="unavailable" if value is None else "ok",
    )
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _calculate_forecast_adjustment(
    today_kwh: float,
    remaining_kwh: float,
    production_kwh: float,
) -> tuple[float | None, float | None, str | None]:
    expected_kwh = today_kwh - remaining_kwh
    if expected_kwh <= 0:
        return None, None, "invalid_denominator"
    if production_kwh <= 0:
        return None, None, "invalid_production"
    factor = production_kwh / expected_kwh
    forecast_adjusted = today_kwh * factor
    return forecast_adjusted, factor, None


def _get_forecast_inputs(
    hass: HomeAssistant,
    config: dict[str, object],
    *,
    pv_forecast_today_entity: str | None = None,
    pv_forecast_remaining_entity: str | None = None,
    pv_production_entity: str | None = None,
) -> tuple[float | None, float | None, float | None, str | None]:
    remaining_sensor = pv_forecast_remaining_entity or config.get(
        CONF_PV_FORECAST_REMAINING
    )
    today_sensor = pv_forecast_today_entity or config.get(CONF_PV_FORECAST_TODAY)
    production_sensor = pv_production_entity or config.get(CONF_PV_PRODUCTION_SENSOR)
    if not remaining_sensor or not today_sensor or not production_sensor:
        return None, None, None, "missing_sensor"

    remaining_state = hass.states.get(remaining_sensor)
    record_input(
        "pv_forecast_remaining",
        source=str(remaining_sensor),
        value=None if remaining_state is None else remaining_state.state,
        status=(
            "missing"
            if remaining_state is None
            else "unavailable"
            if remaining_state.state in {"unknown", "unavailable"}
            else "ok"
        ),
    )
    if remaining_state is None:
        _LOGGER.warning("PV remaining forecast sensor %s unavailable", remaining_sensor)
        return None, None, None, "missing_remaining"

    today_state = hass.states.get(today_sensor)
    record_input(
        "pv_forecast_today",
        source=str(today_sensor),
        value=None if today_state is None else today_state.state,
        status=(
            "missing"
            if today_state is None
            else "unavailable"
            if today_state.state in {"unknown", "unavailable"}
            else "ok"
        ),
    )
    if today_state is None:
        _LOGGER.warning("PV forecast today sensor %s unavailable", today_sensor)
        return None, None, None, "missing_today"

    production_state = hass.states.get(production_sensor)
    record_input(
        "pv_production_sensor",
        source=str(production_sensor),
        value=None if production_state is None else production_state.state,
        status=(
            "missing"
            if production_state is None
            else "unavailable"
            if production_state.state in {"unknown", "unavailable"}
            else "ok"
        ),
    )
    if production_state is None:
        _LOGGER.warning("PV production sensor %s unavailable", production_sensor)
        return None, None, None, "missing_production"

    try:
        remaining_kwh = float(remaining_state.state)
    except (ValueError, TypeError):
        _LOGGER.warning(
            "PV remaining forecast sensor %s has invalid value: %s",
            remaining_sensor,
            remaining_state.state,
        )
        return None, None, None, "invalid_remaining"

    try:
        today_kwh = float(today_state.state)
    except (ValueError, TypeError):
        _LOGGER.warning(
            "PV forecast today sensor %s has invalid value: %s",
            today_sensor,
            today_state.state,
        )
        return None, None, None, "invalid_today"

    try:
        production_kwh = float(production_state.state)
    except (ValueError, TypeError):
        _LOGGER.warning(
            "PV production sensor %s has invalid value: %s",
            production_sensor,
            production_state.state,
        )
        return None, None, None, "invalid_production"

    return today_kwh, remaining_kwh, production_kwh, None
