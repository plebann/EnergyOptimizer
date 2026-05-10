"""Price-related sensors for Energy Optimizer."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorStateClass
from homeassistant.util import dt as dt_util

from ..base import EnergyOptimizerSensor
from ...calculations.price_windows import (
    build_midday_sell_window_result,
    format_sell_window,
)
from ...const import (
    CONF_BUY_PRICE_SENSOR,
    CONF_MIN_ARBITRAGE_PRICE,
    CONF_SELL_PRICE_SENSOR,
    DEFAULT_MIN_ARBITRAGE_PRICE,
    PRICE_UNIT_PLN_PER_KWH,
)


class _PriceValueSensor(EnergyOptimizerSensor):
    """Base sensor for values expressed in PLN/kWh."""

    _attr_native_unit_of_measurement = PRICE_UNIT_PLN_PER_KWH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 3

    @staticmethod
    def _round_value(value: float | None) -> float | None:
        """Normalize output values to 3 decimal places."""
        if value is None:
            return None
        return round(value, 3)


class BuyPriceSensor(_PriceValueSensor):
    """Sensor mirroring the configured buy price source."""

    _attr_translation_key = "buy_price"
    _attr_unique_id = "buy_price"
    _attr_icon = "mdi:cart"

    @property
    def native_value(self) -> float | None:
        """Return the configured buy price."""
        return self._round_value(
            self._get_state_value(self.config.get(CONF_BUY_PRICE_SENSOR))
        )


class SellPriceSensor(_PriceValueSensor):
    """Sensor mirroring the configured sell price source."""

    _attr_translation_key = "sell_price"
    _attr_unique_id = "sell_price"
    _attr_icon = "mdi:cash-fast"

    @property
    def native_value(self) -> float | None:
        """Return the configured sell price."""
        return self._round_value(
            self._get_state_value(self.config.get(CONF_SELL_PRICE_SENSOR))
        )


class MinArbitrageMarginSensor(_PriceValueSensor):
    """Sensor exposing the configured minimum arbitrage margin."""

    _attr_translation_key = "min_arbitrage_margin"
    _attr_unique_id = "min_arbitrage_margin"
    _attr_icon = "mdi:swap-horizontal-bold"

    @property
    def native_value(self) -> float:
        """Return the configured minimum arbitrage margin."""
        configured = self.config.get(
            CONF_MIN_ARBITRAGE_PRICE,
            DEFAULT_MIN_ARBITRAGE_PRICE,
        )
        return round(float(configured or 0.0), 3)


class _MiddaySellWindowBaseSensor(EnergyOptimizerSensor):
    """Base sensor for day-scoped midday sell-price windows."""

    _attr_icon = "mdi:clock-time-eight-outline"
    _payload_key: str
    _day_offset: int = 0

    def __init__(self, coordinator, config_entry, config) -> None:
        """Initialize the sensor with the current coordinator snapshot."""
        super().__init__(coordinator, config_entry, config)
        self._apply_result(self._get_result())

    def _get_result(self):
        """Return the selected midday sell window result for this sensor variant."""
        entity_id = self.config.get(CONF_SELL_PRICE_SENSOR)
        if not entity_id or self.coordinator.data is None:
            return None

        payloads = self.coordinator.data.get("price_payloads")
        if not isinstance(payloads, dict):
            return None

        payload = payloads.get(entity_id)
        if not isinstance(payload, dict):
            return None

        prices = payload.get(self._payload_key)
        if not isinstance(prices, list) or not prices:
            return None

        now_local = dt_util.now() + timedelta(days=self._day_offset)
        return build_midday_sell_window_result(prices, entity_id, now_local=now_local)

    def _apply_result(self, result) -> None:
        """Update cached state and attributes from a computed window result."""
        if result is None:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        self._attr_native_value = format_sell_window(result)
        self._attr_extra_state_attributes = {
            "price": round(result.average_price, 2)
        }

    @property
    def native_value(self) -> str | None:
        """Return the cheapest midday sell-price window as HH:MM-HH:MM, or None."""
        self._apply_result(self._get_result())
        return getattr(self, "_attr_native_value", None)

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        """Return the rounded average price when a valid window exists."""
        self._apply_result(self._get_result())
        return getattr(self, "_attr_extra_state_attributes", {})

    def _handle_coordinator_update(self) -> None:
        """Handle updated coordinator data."""
        self._apply_result(self._get_result())
        super()._handle_coordinator_update()


class MiddaySellWindowSensor(_MiddaySellWindowBaseSensor):
    """Sensor publishing the cheapest 8-quarter-hour midday sell-price window."""

    _attr_translation_key = "midday_sell_window"
    _attr_unique_id = "midday_sell_window"
    _payload_key = "prices_today"


class MiddaySellWindowTomorrowSensor(_MiddaySellWindowBaseSensor):
    """Sensor publishing the cheapest midday sell window for tomorrow."""

    _attr_translation_key = "midday_sell_window_tomorrow"
    _attr_unique_id = "midday_sell_window_tomorrow"
    _payload_key = "prices_tomorrow"
    _day_offset = 1
