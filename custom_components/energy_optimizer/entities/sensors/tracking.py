"""Tracking and diagnostic sensors for Energy Optimizer."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.util import dt as dt_util

from ..base import EnergyOptimizerSensor
from ...helpers import is_test_mode

_LOGGER = logging.getLogger(__name__)


class LastBalancingTimestampSensor(EnergyOptimizerSensor, RestoreSensor):
    """Sensor tracking last battery balancing timestamp."""

    _attr_name = "Last Battery Balancing"
    _attr_unique_id = "last_balancing_timestamp"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"
    _attr_native_value: datetime | None = None
    _attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Restore last state on startup."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in ("unknown", "unavailable"):
                try:
                    self._attr_native_value = datetime.fromisoformat(last_state.state)
                except ValueError:
                    self._attr_native_value = None
            self._attr_extra_state_attributes = last_state.attributes or {}
            _LOGGER.info("Restored LastBalancingTimestampSensor: %s", last_state.state)

    @property
    def native_value(self) -> datetime | None:
        """Return the last balancing timestamp."""
        return self._attr_native_value

    def update_balancing_timestamp(self) -> None:
        """Update balancing timestamp to now."""
        now = dt_util.utcnow()
        self._attr_native_value = now
        self._attr_extra_state_attributes = {
            "timestamp_local": dt_util.now().isoformat(),
        }
        self.async_write_ha_state()


class OptimizationExtraStoredData(ExtraStoredData):
    """Custom ExtraStoredData for LastOptimizationSensor."""

    def __init__(
        self,
        native_value: datetime | None,
        scenario: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the stored data."""
        self.native_value = native_value
        self.scenario = scenario
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        """Return dict representation."""
        return {
            "native_value": self.native_value.isoformat()
            if self.native_value is not None
            else None,
            "scenario": self.scenario,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OptimizationExtraStoredData:
        """Restore from dict."""
        native_value = None
        if data.get("native_value"):
            native_value = datetime.fromisoformat(data["native_value"])
        return cls(
            native_value=native_value,
            scenario=data.get("scenario"),
            details=data.get("details", {}),
        )


class HistoryExtraStoredData(ExtraStoredData):
    """Custom ExtraStoredData for OptimizationHistorySensor."""

    def __init__(
        self,
        native_value: str,
        history: list[dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the stored data."""
        self.native_value = native_value
        self.history = history or []

    def as_dict(self) -> dict[str, Any]:
        """Return dict representation."""
        return {
            "native_value": self.native_value,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryExtraStoredData:
        """Restore from dict."""
        history = data.get("history", [])
        if not isinstance(history, list):
            history = []
        history = history[:50] if len(history) > 50 else history
        return cls(
            native_value=data.get("native_value", "No optimizations yet"),
            history=history,
        )


class LastOptimizationSensor(EnergyOptimizerSensor, RestoreSensor):
    """Sensor tracking last optimization run and decision."""

    _attr_name = "Last Optimization"
    _attr_unique_id = "last_optimization"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"
    _attr_native_value: datetime | None = None
    _attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Restore last state on startup."""
        await super().async_added_to_hass()

        if (extra_data := await self.async_get_last_extra_data()) is not None:
            if isinstance(extra_data, OptimizationExtraStoredData):
                self._attr_native_value = extra_data.native_value
                if extra_data.scenario:
                    self._attr_extra_state_attributes = {
                        "scenario": extra_data.scenario,
                        **extra_data.details,
                    }
                _LOGGER.info(
                    "Restored LastOptimizationSensor: %s (scenario: %s)",
                    self._attr_native_value,
                    extra_data.scenario,
                )
            else:
                _LOGGER.warning("Unexpected extra data type for LastOptimizationSensor")

    @property
    def native_value(self) -> datetime | None:
        """Return the last optimization timestamp."""
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        return self._attr_extra_state_attributes

    @property
    def extra_restore_state_data(self) -> OptimizationExtraStoredData | None:
        """Return extra data to persist."""
        if self._attr_native_value is None:
            return None
        scenario = self._attr_extra_state_attributes.get("scenario")
        details = {
            k: v
            for k, v in self._attr_extra_state_attributes.items()
            if k not in ("scenario", "timestamp_local")
        }
        return OptimizationExtraStoredData(
            native_value=self._attr_native_value,
            scenario=scenario,
            details=details,
        )

    def log_optimization(self, scenario: str, details: dict[str, Any]) -> None:
        """Log an optimization run (called from service)."""
        self._attr_native_value = dt_util.utcnow()
        self._attr_extra_state_attributes = {
            "scenario": scenario,
            "timestamp_local": dt_util.now().isoformat(),
            **details,
        }
        self.async_write_ha_state()
        _LOGGER.debug("Logged optimization: %s - %s", scenario, details)


class TestModeSensor(EnergyOptimizerSensor):
    """Sensor showing whether test mode is enabled."""

    _attr_has_entity_name = True
    _attr_translation_key = "test_mode"
    _attr_unique_id = "test_mode"
    _attr_icon = "mdi:test-tube"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> bool:
        """Return whether test mode is enabled."""
        return is_test_mode(self.config_entry)


class PvForecastCompensationSensor(EnergyOptimizerSensor, RestoreSensor):
    """Sensor storing PV forecast compensation ratio and inputs."""

    _attr_translation_key = "pv_forecast_compensation"
    _attr_unique_id = "pv_forecast_compensation"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_value: float | None = None
    _attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Restore last state and attributes."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._attr_native_value = float(last_state.state)
            except (ValueError, TypeError):
                self._attr_native_value = None

            restored_attrs = dict(last_state.attributes or {})
            self._attr_extra_state_attributes = {
                "forecast_yesterday_kwh": restored_attrs.get(
                    "forecast_yesterday_kwh"
                ),
                "forecast_today_kwh": restored_attrs.get("forecast_today_kwh"),
                "production_yesterday_kwh": restored_attrs.get(
                    "production_yesterday_kwh"
                ),
                "production_today_kwh": restored_attrs.get(
                    "production_today_kwh"
                ),
            }

    @property
    def native_value(self) -> float | None:
        """Return the current compensation ratio."""
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        return self._attr_extra_state_attributes

    def update_compensation(
        self,
        *,
        forecast_today_kwh: float | None,
        production_today_kwh: float | None,
        forecast_yesterday_kwh: float | None,
        production_yesterday_kwh: float | None,
    ) -> None:
        """Update attributes and recompute compensation factor."""

        def _ratio(production: float | None, forecast: float | None) -> float | None:
            if production is None or forecast is None:
                return None
            if forecast <= 0 or production < 0:
                return None
            return production / forecast

        ratio_today = _ratio(production_today_kwh, forecast_today_kwh)
        ratio_yesterday = _ratio(production_yesterday_kwh, forecast_yesterday_kwh)

        if ratio_today is not None and ratio_yesterday is not None:
            factor = (ratio_yesterday + ratio_today * 2.0) / 3.0
        elif ratio_today is not None:
            factor = ratio_today
        elif ratio_yesterday is not None:
            factor = ratio_yesterday
        else:
            factor = None

        self._attr_native_value = round(factor, 4) if factor is not None else None
        self._attr_extra_state_attributes = {
            "forecast_yesterday_kwh": (
                round(forecast_yesterday_kwh, 2)
                if forecast_yesterday_kwh is not None
                else None
            ),
            "forecast_today_kwh": (
                round(forecast_today_kwh, 2)
                if forecast_today_kwh is not None
                else None
            ),
            "production_yesterday_kwh": (
                round(production_yesterday_kwh, 2)
                if production_yesterday_kwh is not None
                else None
            ),
            "production_today_kwh": (
                round(production_today_kwh, 2)
                if production_today_kwh is not None
                else None
            ),
        }
        self.async_write_ha_state()


class OptimizationHistorySensor(EnergyOptimizerSensor, RestoreSensor):
    """Sensor showing recent optimization history as text."""

    _attr_name = "Optimization History"
    _attr_unique_id = "optimization_history"
    _attr_icon = "mdi:history"
    _attr_native_value: str = "No optimizations yet"

    def __init__(
        self,
        coordinator,
        config_entry,
        config: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry, config)
        self._history: list[dict[str, Any]] = []

    async def async_added_to_hass(self) -> None:
        """Restore history on startup."""
        await super().async_added_to_hass()

        if (extra_data := await self.async_get_last_extra_data()) is not None:
            restored_data = None
            if isinstance(extra_data, HistoryExtraStoredData):
                restored_data = extra_data
            elif hasattr(extra_data, "as_dict"):
                restored_data = HistoryExtraStoredData.from_dict(extra_data.as_dict())

            if restored_data is not None:
                self._attr_native_value = restored_data.native_value
                self._history = restored_data.history
                _LOGGER.info(
                    "Restored OptimizationHistorySensor: %d entries",
                    len(self._history),
                )
            else:
                _LOGGER.warning("Unexpected extra data type for OptimizationHistorySensor")

    @property
    def native_value(self) -> str:
        """Return the most recent optimization as text."""
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the optimization history."""
        return {
            "history": self._history,
        }

    @property
    def extra_restore_state_data(self) -> HistoryExtraStoredData:
        """Return extra data to persist."""
        return HistoryExtraStoredData(
            native_value=self._attr_native_value,
            history=self._history,
        )

    def add_entry(self, scenario: str, details: dict[str, Any]) -> None:
        """Add an optimization entry to the history."""
        entry = {
            "timestamp": dt_util.now().isoformat(),
            "scenario": scenario,
            **details,
        }
        self._history.insert(0, entry)
        self._history = self._history[:50]
        self._attr_native_value = f"{scenario} - {details.get('result', 'completed')}"
        self.async_write_ha_state()
